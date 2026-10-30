# Copyright 2026 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
pyperf orchestration and scoring.

Every case measures the same work twice: ``reference`` (plain Python) and ``library``
(``eventlib``). The case result is ``median(library) / median(reference)`` — the factor the
framework adds — and the suite score is the **median of those ratios**, so a single noisy
case cannot move the headline number.

The median is used rather than the mean because pyperf reports outliers (scheduler noise,
GC pauses, CPU frequency changes) and the median ignores them.
"""

import dataclasses
import json
import math
import statistics
from pathlib import Path
from typing import Any

import pyperf  # type: ignore[import-untyped]

from .case import Case
from .cases import select_cases
from .errors import BenchmarkError

SUMMARY_FORMAT = 1
"""Version of the summary file written by `save_suite` and read by `load_suite`."""


@dataclasses.dataclass(frozen=True, slots=True)
class CaseResult:
    """Measured outcome of a single case.

    ``reference`` and ``library`` are medians in seconds. The ``*_stdev`` fields are the
    standard deviation of the **per-run means** and are ``None`` when a side has fewer
    than two runs.
    """

    case: Case
    reference: float
    library: float
    reference_stdev: float | None = None
    library_stdev: float | None = None

    @classmethod
    def from_benchmarks(
        cls,
        case: Case,
        reference: pyperf.Benchmark,
        library: pyperf.Benchmark,
    ) -> "CaseResult":
        """Summarise the two pyperf benchmarks of one case."""
        return cls(
            case=case,
            reference=reference.median(),
            library=library.median(),
            reference_stdev=_run_stdev(reference),
            library_stdev=_run_stdev(library),
        )

    @property
    def ratio(self) -> float:
        """Library cost divided by reference cost (1.0 = same speed)."""
        if self.reference <= 0:
            return float("inf")
        return self.library / self.reference

    @property
    def ratio_stdev(self) -> float | None:
        """One-sigma spread of `ratio`, propagated from both sides.

        ``ratio * hypot(rel_stdev(reference), rel_stdev(library))``. ``None`` when either
        side has no dispersion information.
        """
        if self.reference_stdev is None or self.library_stdev is None:
            return None
        if self.reference <= 0 or self.library <= 0:
            return None
        relative = math.hypot(
            self.reference_stdev / self.reference,
            self.library_stdev / self.library,
        )
        return self.ratio * relative

    @property
    def scored(self) -> bool:
        """Whether the case contributes to the overall score."""
        return self.case.scored


@dataclasses.dataclass(frozen=True, slots=True)
class SuiteResult:
    """Result of a whole run."""

    results: tuple[CaseResult, ...]
    metadata: dict[str, Any]

    @property
    def scored_results(self) -> tuple[CaseResult, ...]:
        """Results that contribute to the overall score."""
        return tuple(result for result in self.results if result.scored)

    @property
    def score(self) -> float:
        """Median of the per-case ratios of all scored cases."""
        ratios = [result.ratio for result in self.scored_results]
        if not ratios:
            return float("nan")
        return statistics.median(ratios)

    def by_group(self) -> dict[str, tuple[CaseResult, ...]]:
        """Group results by their case group, preserving the canonical order."""
        groups: dict[str, list[CaseResult]] = {}
        for result in self.results:
            groups.setdefault(result.case.group, []).append(result)
        return {name: tuple(items) for name, items in groups.items()}


def _run_stdev(bench: pyperf.Benchmark) -> float | None:
    """Standard deviation of the per-run means, or ``None`` with fewer than two runs.

    Values inside one process share interpreter state, CPU frequency and cache warmth, so
    they are correlated. Pooling them (``Benchmark.stdev()``) understates the
    between-process variance that actually drives run-to-run reproducibility.
    """
    means = [statistics.mean(run.values) for run in bench.get_runs() if run.values]
    return statistics.stdev(means) if len(means) >= 2 else None


# --------------------------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------------------------
def _skipped() -> None:
    """Placeholder for a task that this process does not own. Never executed."""


_SKIPPED = _skipped  # pylint: disable=invalid-name
"""Sentinel callable passed to pyperf for tasks owned by another process."""


def run_cases(cases: tuple[Case, ...], runner: pyperf.Runner) -> SuiteResult:
    """
    Measure every selected case with an already configured pyperf runner.

    The caller owns the runner because pyperf allows exactly one per process and the CLI
    flags (``-p``, ``-n``, ``--fast``, …) are parsed from the real ``sys.argv``.

    pyperf re-spawns this program once per benchmark and tells each worker which task it
    owns via ``--worker-task``. Building a case's state is not free (event systems,
    warm-up emits), so the factories are only invoked for the task the current process
    actually owns.
    """
    args = runner.parse_args()
    # ``None`` in the parent process, the owned task index inside a worker.
    worker_task = args.worker_task

    raw: dict[str, pyperf.Benchmark] = {}
    task_index = 0

    for case in cases:
        metadata = {"case": case.id, "group": case.group, "description": case.description}
        for name, factory, is_async in (
            (case.reference_name, case.reference, case.is_async),
            (case.library_name, case.library, case.is_async),
        ):
            owns_task = worker_task is None or worker_task == task_index
            task_index += 1

            # `bench_func` must be called for every task, even in a worker that does not
            # own it: pyperf advances its own task counter inside that call, and skipping
            # the call would desynchronise it from the task index the worker was given.
            # The placeholder is never executed - pyperf returns before touching it.
            func = factory() if owns_task else _SKIPPED
            bench_func = runner.bench_async_func if is_async else runner.bench_func
            bench = bench_func(name, func, metadata=metadata, inner_loops=case.inner_loops)

            # bench_* returns None for every worker process except the one that owns the
            # task, so only the parent process reaches this point with real results.
            if bench is not None:
                raw[name] = bench

    # A worker process only measures one task and reports it through pyperf's pipe; it
    # has no results to aggregate and must not try.
    if worker_task is not None:
        return SuiteResult(results=(), metadata={})

    return _aggregate(cases, raw)


_CASE_METADATA_KEYS = ("case", "group", "description", "name")
"""Metadata keys that describe one benchmark rather than the machine.

``BenchmarkSuite.get_metadata()`` keeps the keys that agree across all benchmarks, so a
single-case run would otherwise carry that case's name and description into the summary.
"""


def _aggregate(cases: tuple[Case, ...], raw: dict[str, pyperf.Benchmark]) -> SuiteResult:
    """Turn the per-benchmark results into per-case ratios and the suite score."""
    results: list[CaseResult] = []
    for case in cases:
        bench_ref = raw.get(case.reference_name)
        bench_lib = raw.get(case.library_name)
        if bench_ref is None or bench_lib is None:
            raise BenchmarkError(f"no result recorded for case {case.id!r}")
        results.append(CaseResult.from_benchmarks(case, bench_ref, bench_lib))

    # Per-benchmark metadata includes the case name, so use the metadata common to every
    # benchmark instead: interpreter, host, CPU, load, … without per-case keys.
    metadata = pyperf.BenchmarkSuite(list(raw.values())).get_metadata() if raw else {}
    for key in _CASE_METADATA_KEYS:
        metadata.pop(key, None)
    return SuiteResult(results=tuple(results), metadata=metadata)


# --------------------------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------------------------
def save_suite(result: SuiteResult, path: Path) -> None:
    """Write the summary (medians, spreads, ratios, score) as JSON."""
    payload = {
        "format": SUMMARY_FORMAT,
        "score": result.score,
        "metadata": result.metadata,
        "cases": [
            {
                "id": item.case.id,
                "group": item.case.group,
                "description": item.case.description,
                "scored": item.scored,
                "reference": item.reference,
                "library": item.library,
                "reference_stdev": item.reference_stdev,
                "library_stdev": item.library_stdev,
                "ratio": item.ratio,
            }
            for item in result.results
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_suite(path: Path) -> SuiteResult:
    """Read a summary written by `save_suite`."""
    if not path.exists():
        raise BenchmarkError(f"{path}: no such file")
    payload = json.loads(path.read_text(encoding="utf-8"))

    if "benchmarks" in payload:
        raise BenchmarkError(
            f"{path}: this is a pyperf-native result file, not a benchmark summary.\n"
            "  Use `benchmark run --summary FILE` to write a summary."
        )

    version = payload.get("format")
    if version != SUMMARY_FORMAT:
        raise BenchmarkError(f"{path}: unsupported summary format {version!r}")

    by_id = {case.id: case for case in select_cases(None)}
    results: list[CaseResult] = []
    for item in payload["cases"]:
        case = by_id.get(item["id"])
        if case is None:
            raise BenchmarkError(f"{path}: unknown case {item['id']!r}; the case registry changed")
        results.append(
            CaseResult(
                case=case,
                reference=item["reference"],
                library=item["library"],
                reference_stdev=item.get("reference_stdev"),
                library_stdev=item.get("library_stdev"),
            )
        )
    return SuiteResult(results=tuple(results), metadata=payload.get("metadata", {}))


# --------------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------------
def _format_seconds(value: float) -> str:
    """Format a duration with a unit that keeps three significant digits."""
    for unit, scale in (("s", 1.0), ("ms", 1e-3), ("µs", 1e-6), ("ns", 1e-9)):
        if value >= scale or unit == "ns":
            return f"{value / scale:.3g} {unit}"
    return f"{value:.3g} s"


def _format_seconds_with_stdev(value: float, stdev: float | None) -> str:
    """Format a duration with its one-sigma spread, or alone when unknown."""
    if stdev is None:
        return _format_seconds(value)
    return f"{_format_seconds(value)} ± {_format_seconds(stdev)}"


def _format_sigma(sigma: float | None) -> str:
    """Format the one-sigma spread of a ratio."""
    return "n/a" if sigma is None else f"±{sigma:.2f}"


def format_markdown(result: SuiteResult) -> str:
    """Render the full result as a Markdown report."""
    lines = ["# eventlib-py benchmark", ""]

    metadata = result.metadata
    if metadata:
        python = metadata.get("python_version", "unknown")
        implementation = metadata.get("python_implementation", "")
        host = metadata.get("hostname", "unknown")
        cpu = metadata.get("cpu_model_name") or metadata.get("cpu_model") or "unknown CPU"
        lines.append(f"- Python: {implementation} {python}".replace("  ", " "))
        lines.append(f"- Host: {host} ({cpu})")
        lines.append("")

    lines.append(f"**Overall score (median of per-case ratios): {result.score:.2f}x**")
    lines.append("")
    lines.append("A score of `1.00x` means the library costs exactly as much as the hand-written")
    lines.append("reference; `1.50x` means it costs 50 % more.")
    lines.append("")

    for group, items in result.by_group().items():
        lines.append(f"## {group}")
        lines.append("")
        lines.append("| Case | Reference | Library | Ratio | ±1σ | Scored | Description |")
        lines.append("|:-----|----------:|--------:|------:|----:|:-------|:------------|")
        for item in items:
            lines.append(
                f"| `{item.case.name}` "
                f"| {_format_seconds_with_stdev(item.reference, item.reference_stdev)} "
                f"| {_format_seconds_with_stdev(item.library, item.library_stdev)} "
                f"| {item.ratio:.2f}x | {_format_sigma(item.ratio_stdev)} "
                f"| {'yes' if item.scored else 'no'} | {item.case.description} |"
            )
        lines.append("")

    lines.append("±1σ is the spread of the ratio, propagated from the standard deviation of the")
    lines.append("per-run means. `n/a` means a side had fewer than two runs.")
    lines.append("")

    return "\n".join(lines)


__all__ = [
    "SUMMARY_FORMAT",
    "CaseResult",
    "SuiteResult",
    "format_markdown",
    "load_suite",
    "run_cases",
    "save_suite",
]
