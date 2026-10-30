# Copyright 2026 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Tests for the benchmark suite's own logic.

The measurements themselves are pyperf's responsibility and are not unit tested; what is
tested here is the part that could silently be wrong and invalidate every number: the case
registry, the median-based scoring and the summary round-trip.
"""

import json
import math
from pathlib import Path

import pyperf  # type: ignore[import-untyped]
import pytest

from benchmark.case import Case
from benchmark.cases import ALL_CASES, BY_ID, GROUPS, select_cases
from benchmark.cli import DEFAULT_PROCESSES, _with_default_processes, _writes_pyperf_output
from benchmark.errors import BenchmarkError
from benchmark.suite import (
    SUMMARY_FORMAT,
    CaseResult,
    SuiteResult,
    format_markdown,
    load_suite,
    save_suite,
)

# pylint: disable=missing-function-docstring


def _case(name: str, group: str = "test", scored: bool = True) -> Case:
    """Build a trivial case for the scoring tests."""
    return Case(
        name=name,
        group=group,
        description=f"{name} description",
        reference=lambda: (lambda: None),
        library=lambda: (lambda: None),
        scored=scored,
    )


def _result(
    case: Case,
    reference: float,
    library: float,
    reference_stdev: float | None = None,
    library_stdev: float | None = None,
) -> CaseResult:
    """Build a case result from the two medians."""
    return CaseResult(
        case=case,
        reference=reference,
        library=library,
        reference_stdev=reference_stdev,
        library_stdev=library_stdev,
    )


# --------------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------------
def test_case_ids_are_unique():
    assert len({case.id for case in ALL_CASES}) == len(ALL_CASES)


def test_case_names_are_unique_per_group():
    for group, cases in GROUPS.items():
        names = [case.name for case in cases]
        assert len(set(names)) == len(names), f"duplicate case name in group {group}"


def test_every_group_has_cases():
    for group, cases in GROUPS.items():
        assert cases, f"group {group} is empty"


def test_select_all_returns_every_case():
    assert select_cases(None) == ALL_CASES
    assert select_cases(["all"]) == ALL_CASES


def test_select_group():
    for group, cases in GROUPS.items():
        assert select_cases([group]) == cases


def test_select_full_id():
    case = ALL_CASES[0]
    assert select_cases([case.id]) == (case,)


def test_select_bare_name():
    case = ALL_CASES[0]
    assert select_cases([case.name]) == (case,)


def test_select_preserves_canonical_order():
    first, second = ALL_CASES[0], ALL_CASES[1]
    assert select_cases([second.id, first.id]) == (first, second)


def test_select_is_deduplicated():
    case = ALL_CASES[0]
    assert select_cases([case.id, case.id]) == (case,)


def test_select_unknown_raises():
    with pytest.raises(BenchmarkError, match="unknown case"):
        select_cases(["does-not-exist"])


def test_by_id_matches_registry():
    assert BY_ID == {case.id: case for case in ALL_CASES}


# --------------------------------------------------------------------------------------------
# CLI helpers
# --------------------------------------------------------------------------------------------
def test_default_processes_are_injected():
    assert _with_default_processes([]) == ["--processes", str(DEFAULT_PROCESSES)]


def test_explicit_processes_are_respected():
    for args in (["-p", "4"], ["--processes", "4"], ["--processes=4"]):
        assert _with_default_processes(list(args)) == args


def test_presets_are_not_overridden():
    for args in (["--fast"], ["--rigorous"]):
        assert _with_default_processes(list(args)) == args


def test_detects_pyperf_output_flag():
    assert _writes_pyperf_output(["-o", "out.json"])
    assert _writes_pyperf_output(["--output", "out.json"])
    assert _writes_pyperf_output(["--output=out.json"])


def test_no_pyperf_output_flag():
    assert not _writes_pyperf_output([])
    assert not _writes_pyperf_output(["--fast", "--quiet"])


# --------------------------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------------------------
def test_score_is_median_of_ratios():
    # Ratios 1, 2, 10 -> median 2 (not the mean 4.33).
    results = (
        _result(_case("a"), 100.0, 100.0),
        _result(_case("b"), 100.0, 200.0),
        _result(_case("c"), 100.0, 1000.0),
    )
    suite = SuiteResult(results=results, metadata={})
    assert suite.score == pytest.approx(2.0)


def test_score_ignores_unscored_cases():
    results = (
        _result(_case("a"), 100.0, 100.0),
        _result(_case("b"), 100.0, 300.0),
        _result(_case("diagnostic", scored=False), 1.0, 1000.0),
    )
    suite = SuiteResult(results=results, metadata={})
    assert suite.score == pytest.approx(2.0)


def test_score_of_empty_suite_is_nan():
    suite = SuiteResult(results=(), metadata={})
    assert math.isnan(suite.score)


def test_ratio_handles_zero_reference():
    assert _result(_case("a"), 0.0, 1.0).ratio == float("inf")


def test_ratio_stdev_propagates_both_sides():
    result = _result(_case("a"), 1.0, 2.0, reference_stdev=0.1, library_stdev=0.4)
    # ratio 2.0; relative spreads 0.1 and 0.2 -> 2 * hypot(0.1, 0.2)
    assert result.ratio_stdev == pytest.approx(2.0 * math.hypot(0.1, 0.2))


def test_ratio_stdev_is_none_without_dispersion():
    assert _result(_case("a"), 1.0, 2.0).ratio_stdev is None
    assert _result(_case("a"), 1.0, 2.0, reference_stdev=0.1).ratio_stdev is None


def test_aggregate_strips_per_case_metadata():
    """Metadata describes the machine, not one benchmark, so per-case keys are removed."""
    from benchmark.suite import _aggregate  # pylint: disable=import-outside-toplevel

    case = ALL_CASES[0]
    shared = {"case": case.id, "group": case.group, "hostname": "test"}
    bench = pyperf.Benchmark([pyperf.Run(values=[1e-6, 1.1e-6], metadata={**shared, "name": case.reference_name})])
    library = pyperf.Benchmark([pyperf.Run(values=[2e-6, 2.1e-6], metadata={**shared, "name": case.library_name})])

    suite = _aggregate((case,), {case.reference_name: bench, case.library_name: library})

    assert "case" not in suite.metadata
    assert "group" not in suite.metadata
    assert "name" not in suite.metadata
    assert suite.metadata["hostname"] == "test"


def test_by_group_preserves_order():
    a = _result(_case("a", group="one"), 1.0, 1.0)
    b = _result(_case("b", group="two"), 1.0, 1.0)
    c = _result(_case("c", group="one"), 1.0, 1.0)
    grouped = SuiteResult(results=(a, b, c), metadata={}).by_group()
    assert list(grouped) == ["one", "two"]
    assert grouped["one"] == (a, c)


# --------------------------------------------------------------------------------------------
# Persistence and reporting
# --------------------------------------------------------------------------------------------
def test_summary_round_trip(tmp_path: Path):
    results = (
        _result(ALL_CASES[0], 1e-6, 2e-6, reference_stdev=1e-7, library_stdev=2e-7),
        _result(ALL_CASES[1], 3e-6, 4e-6),
    )
    suite = SuiteResult(results=results, metadata={"hostname": "test"})
    path = tmp_path / "summary.json"

    save_suite(suite, path)
    loaded = load_suite(path)

    assert loaded.score == pytest.approx(suite.score)
    assert loaded.metadata["hostname"] == "test"
    assert [item.case.id for item in loaded.results] == [item.case.id for item in results]
    for original, restored in zip(results, loaded.results):
        assert restored.reference == pytest.approx(original.reference)
        assert restored.library == pytest.approx(original.library)
        assert restored.reference_stdev == original.reference_stdev
        assert restored.library_stdev == original.library_stdev


def test_summary_is_valid_json(tmp_path: Path):
    suite = SuiteResult(results=(_result(ALL_CASES[0], 1.0, 2.0),), metadata={})
    path = tmp_path / "summary.json"
    save_suite(suite, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format"] == SUMMARY_FORMAT
    assert payload["score"] == pytest.approx(2.0)
    assert payload["cases"][0]["id"] == ALL_CASES[0].id
    assert payload["cases"][0]["reference"] == pytest.approx(1.0)


def test_load_rejects_pyperf_native_file(tmp_path: Path):
    """A pyperf-native result must fail with an actionable message, not a KeyError."""
    path = tmp_path / "pyperf.json"
    path.write_text(json.dumps({"version": "1.0", "benchmarks": []}), encoding="utf-8")
    with pytest.raises(BenchmarkError, match="pyperf-native"):
        load_suite(path)


def test_load_rejects_unknown_format(tmp_path: Path):
    path = tmp_path / "summary.json"
    path.write_text(json.dumps({"format": 999, "cases": []}), encoding="utf-8")
    with pytest.raises(BenchmarkError, match="unsupported summary format"):
        load_suite(path)


def test_load_rejects_unknown_case(tmp_path: Path):
    path = tmp_path / "summary.json"
    payload = {
        "format": SUMMARY_FORMAT,
        "score": 1.0,
        "metadata": {},
        "cases": [{"id": "nope.nope", "reference": 1.0, "library": 1.0}],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BenchmarkError, match="unknown case"):
        load_suite(path)


def test_load_rejects_missing_file(tmp_path: Path):
    with pytest.raises(BenchmarkError, match="no such file"):
        load_suite(tmp_path / "absent.json")


def test_markdown_report_contains_score_and_every_case():
    results = tuple(_result(case, 1e-6, 2e-6) for case in ALL_CASES)
    suite = SuiteResult(results=results, metadata={"hostname": "test", "python_version": "3.12.0"})

    report = format_markdown(suite)

    assert "2.00x" in report
    for case in ALL_CASES:
        assert f"`{case.name}`" in report
    for group in GROUPS:
        assert f"## {group}" in report


def test_markdown_report_marks_diagnostic_cases():
    report = format_markdown(SuiteResult(results=(_result(_case("diag", scored=False), 1.0, 2.0),), metadata={}))
    assert "| no |" in report


def test_markdown_report_shows_stdev_and_sigma():
    result = _result(_case("a"), 1e-6, 2e-6, reference_stdev=1e-7, library_stdev=2e-7)
    report = format_markdown(SuiteResult(results=(result,), metadata={}))

    assert "± 100 ns" in report
    assert "± 200 ns" in report
    assert "±1σ" in report


def test_markdown_report_marks_missing_dispersion_as_na():
    report = format_markdown(SuiteResult(results=(_result(_case("a"), 1.0, 2.0),), metadata={}))
    assert "n/a" in report
