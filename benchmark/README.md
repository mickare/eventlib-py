<!-- Copyright 2026 Michael Käser -->
<!-- SPDX-License-Identifier: (Apache-2.0 OR MIT) -->
# eventlib-py benchmark suite

A [pyperf](https://github.com/psf/pyperf) benchmark suite for `eventlib-py`.

Every case measures the **same work twice**: once as hand-written Python (`reference`) and
once through the event system (`library`). The result is the factor the framework adds, and
the suite's overall score is the **median of those per-case factors**.

- `1.00x` — the library costs exactly as much as the hand-written reference.
- `1.50x` — the library costs 50 % more.
- Lower is better.

---

## Quick start

The benchmark is a standalone poetry project in this directory (see
[pyproject.toml](./pyproject.toml)). Install it and its dependencies — including
`eventlib-py` itself from the repository root — with:

```bash
cd benchmark
poetry install
poetry run benchmark list
```

From the repository root, use `poetry -C benchmark run benchmark …`.

```bash
# Everything, with a report and a summary file
poetry run benchmark run --summary results/latest.json

# A quick smoke run
poetry run benchmark run --fast --quiet

# One group
poetry run benchmark run --select micro

# Draw the graphs from a previous run
poetry run benchmark render --summary results/latest.json --output results/latest.png
```

---

## Commands

| Command | Purpose |
|:--------|:--------|
| `benchmark list` | Show every case, grouped, marking the diagnostic ones. |
| `benchmark run` | Measure the selected cases, print a Markdown report, write a summary. |
| `benchmark render` | Draw the comparison and overhead graphs (window, or `-o FILE`). |

Anything the suite does not recognise is forwarded to pyperf, so `--fast`, `--rigorous`,
`-p/--processes`, `-n/--values`, `-w/--warmups`, `--affinity`, `--quiet` and the rest work
unchanged. `benchmark` with no arguments prints both help pages.

`run` defaults to **40 worker processes** per benchmark instead of pyperf's 20. Dispatch
benchmarks run in the nanosecond range, where process-to-process jitter is large relative
to the mean; 20 runs routinely trip pyperf's "not enough samples" warning. Pass
`-p/--processes` to override, or use `--fast` / `--rigorous`, which keep their own presets.

---

## What is measured

Cases are grouped by the question they answer.

### `macro` — end-to-end dispatch

One emit with every supported handler kind subscribed: two async context managers, two
sync context managers, two sync handlers and one async handler. This is the successor of the
original benchmark and the closest thing to a headline number.

### `micro` — one dimension at a time

Handlers are no-ops, so a measured difference is attributable to the framework.

| Case | Dimension |
|:-----|:----------|
| `emit_sync_1 / _10 / _100` | Sync dispatch, handler-count scaling |
| `emit_async_sync_1 / _10` | Async dispatch of *sync* handlers (coroutine bridging) |
| `emit_async_async_1 / _10` | Async dispatch of async handlers |
| `emit_sync_context` | Sync dispatch with a context manager (`ExitStack`) |
| `emit_async_context` | Async dispatch with an async context manager (`AsyncExitStack`) |
| `inherited_dispatch` | Event inheriting from two event classes (chain merge) |
| `subscribe_1 / _10 / _100` | Subscription setup cost and its scaling |
| `emit_zero_sub` | Cached but empty chain — the framework floor *(diagnostic)* |
| `emit_zero_sub_cold` | Empty chain rebuilt on every emit *(diagnostic)* |

The two diagnostic cases have no fair hand-written twin, so they are measured and reported
but **excluded from the score**.

### `journey` — what users actually build

Reproduced from [`examples/`](../examples), these measure realistic scenarios rather than
isolated primitives:

| Case | Scenario |
|:-----|:---------|
| `chat_cancel` | Priority-ordered handlers with cancellation (`use_cases/chat.py`) |
| `plugin_lifecycle` | Lifecycle events observed through a parent event class (`use_cases/plugin_system.py`) |
| `worker_queue_sync` | Drain a batch of queued events with sync handlers (`use_cases/worker_queue.py`) |
| `worker_queue_async` | Same, with async handlers |
| `isolated_systems` | Two systems that must not see each other (`isolated_systems.py`) |
| `attrs_event` | Event declared with `attrs` (`support_attrs.py`) |
| `pydantic_event` | Validated Pydantic event (`support_pydantic.py`) |
| `diamond_inheritance` | Diamond-inherited event reaching each handler once (`complex_inheritance.py`) |
| `copied_system` | Copy a system and extend the copy (`copied_systems.py`) *(diagnostic)* |

---

## Reading the results

`run` prints a Markdown report and writes the same data as JSON:

```markdown
**Overall score (median of per-case ratios): 3.51x**

## micro

| Case | Reference | Library | Ratio | ±1σ | Scored | Description |
|:-----|----------:|--------:|------:|----:|:-------|:------------|
| `emit_sync_1` | 93.3 ns ± 4.1 ns | 294 ns ± 18 ns | 3.15x | ±0.21 | yes | Sync emit with 1 no-op handler |
```

The summary file contains the medians, their spreads, the ratios and the metadata of the
machine, which is what `render` consumes:

```json
{
  "format": 1,
  "score": 3.51,
  "metadata": { "python_version": "3.14.7", "hostname": "sol", "cpu_model_name": "…" },
  "cases": [
    { "id": "micro.emit_sync_1", "group": "micro", "scored": true,
      "reference": 9.33e-08, "library": 2.94e-07,
      "reference_stdev": 4.1e-09, "library_stdev": 1.8e-08,
      "ratio": 3.15 }
  ]
}
```

### Why the median?

pyperf reports outliers: scheduler noise, GC pauses, CPU frequency changes. The mean is
sensitive to them, the median is not. The suite therefore uses the median of each measured
series *and* the median of the per-case ratios, so one noisy case cannot move the headline
number.

Robustness is not precision, though: the median tells you nothing about how much the
number would move on a rerun. That is what the `±1σ` column is for.

### Uncertainty

Every ratio carries a one-sigma spread, propagated from both sides:

```
ratio_stdev = ratio * hypot(rel_stdev(reference), rel_stdev(library))
rel_stdev(side) = stdev(side) / median(side)
```

`stdev` is taken over **per-run means**, not pooled values. Values inside one process share
interpreter state, CPU frequency and cache warmth, so they are correlated; pooling them
(`Benchmark.stdev()`) understates the between-process variance that actually drives
run-to-run reproducibility.

`±1σ` is a spread, not pyperf's warning criterion. pyperf asks for 95 % certainty that the
*mean* varies by less than 1 %, with a 2× safety factor. Our interval answers a narrower
question and will look tighter. They are not contradictory.

**The score has no confidence interval.** The cases are a curated set, not a random sample,
so a CI for the score would be meaningless.

### Graphs

`benchmark render` draws two panels from a summary, sharing one case axis:

1. **Cost per case** — reference vs. library, log scale (the cases span several orders of
   magnitude).
2. **Overhead factor** — library / reference per case, ordered worst first, with a dashed
   line at `1.0` (parity), a solid line at the overall score, and `±1σ` error bars.
   Diagnostic cases are drawn faded and labelled in the legend.

![Rendered benchmark](./benchmark_overview_py314.png)

---

## Comparing runs

```bash
poetry run benchmark run --summary results/baseline.json
# … change something …
poetry run benchmark run --summary results/after.json
```

Each run prints its own per-case table and overall score, so the two reports can be read
off directly. For a statistical before/after test, keep pyperf's native output and use
`pyperf compare_to` (see below).

When comparing runs:

- Compare **ratios**, not absolute times. A slower machine cancels out; absolute timings
  do not.
- Prefer runs made back-to-back on the same machine and interpreter.
- Treat sub-5 % differences as noise unless the `±1σ` intervals are clearly separated.

### pyperf interoperability

The suite writes its own summary, but every benchmark it runs is a normal pyperf benchmark.
If you want pyperf's native output (for `pyperf compare_to`, `pyperf stats`, `pyperf hist`),
just ask pyperf for it — unknown options are forwarded:

```bash
# Record a baseline, then a candidate, as pyperf-native files
poetry run benchmark run --select micro -o results/micro-baseline.json
# … change something …
poetry run benchmark run --select micro -o results/micro.json

# Compare them with pyperf's own tooling
poetry run python -m pyperf compare_to results/micro-baseline.json results/micro.json --table
```

When `-o/--output` is used, the suite does **not** also write its derived summary — you get
exactly the file you asked for. Use `--summary FILE` if you want both.

---

## Tips

- **Use `-O`** to disable assertions, matching production. The library's `assert_not_*`
  checks are active under `__debug__`:
  `poetry run python -O -m benchmark run --summary results/o.json`.
  The suite forwards the interpreter's optimisation flags to its worker processes.
- **Use `nice -n -20`** to give the benchmark a higher priority on a busy machine.
- **Use `--quiet`** to hide pyperf's per-benchmark progress when scripting. Do not use it
  to hide the "not enough samples" warning: that warning is real, and the `±1σ` column is
  the suite's own answer to it. If the spread is too wide for your purpose, raise
  `-p/--processes`.
- **Don't compare across machines or interpreters** — compare ratios, and prefer runs made
  back-to-back on the same machine.
- **Async cases use pyperf's `bench_async_func`**, which enters the event loop once per
  calibrated batch. The reported value is per operation, not per loop entry.

---

## Profiling

The suite tells you *how much*. For *where*, see
[`benchmark/profiling/README.md`](./benchmark/profiling/README.md) — `line_profiler`,
`pyinstrument`, `py-spy` and `memray` scenarios, plus an analysis workflow.

---

## Layout

```
benchmark/
├── benchmark/
│   ├── case.py            Case model (reference + library factories, metadata)
│   ├── cases/
│   │   ├── registry.py    Groups, lookup, --select resolution
│   │   ├── macro.py       End-to-end mixed dispatch
│   │   ├── micro.py       Single-dimension dispatch measurements
│   │   └── journey.py     Realistic user scenarios from examples/
│   ├── suite.py           pyperf orchestration, median scoring, summary I/O, report
│   ├── render.py          Matplotlib graphs
│   ├── cli.py             list / run / render
│   └── profiling/         line_profiler scenarios + profiler workflow docs
├── tests/                 Tests for the registry, scoring and summary round-trip
└── results/               Summaries and figures (git-ignored)
```
