# Profiling & Performance Analysis

Tooling to measure, attribute and improve the runtime performance of `eventlib-py`
without changing its public interface.

This directory is **not** a benchmark of user code — it isolates the *framework overhead*
of the event dispatch path. All scripts run against the `benchmark` poetry project,
which already depends on the local `eventlib` package in editable mode.

---

## Contents

| File | Purpose |
|:-----|:--------|
| `micro.py` | `pyperf` micro-benchmarks. One scenario per dimension of dispatch cost. Produces statistically sound JSON results that can be compared across revisions. |
| `lines.py` | `line_profiler` scenarios. Attributes cost to individual **lines** inside `EventChain.call`, `call_async`, `_get_chain`, `add_subscriber`, … |
| `profiling_results/` | Baseline and candidate result files (`*.json`) written by `micro.py`. |

The surrounding `benchmark/` project (`benchmark/benchmark.py`, `benchmark/cases/`)
remains the *end-to-end* comparison against a hand-written reference implementation.
The scripts here answer a different question: **where inside the library does the time go?**

---

## Setup

The tools live in the dedicated `profiler` dependency group so the library itself keeps
its "no runtime dependencies" property:

```bash
cd benchmark
poetry install --with=profiler
```

---

## Quick start

```bash
cd benchmark

# 1. Record a baseline
poetry run python -m benchmark.profiling.micro -o profiling_results/baseline.json

# 2. Change something, record again
poetry run python -m benchmark.profiling.micro -o profiling_results/after.json

# 3. Compare with statistics
poetry run python -m pyperf compare_to profiling_results/baseline.json profiling_results/after.json --table
```

`pyperf compare_to` reports a per-benchmark ratio and marks results that are not
statistically significant, so you can tell a real improvement from noise.

---

## `micro.py` — micro-benchmarks

Each benchmark measures **one** dispatch dimension, so handler cost never masks framework
cost. The full set:

| Benchmark | What it measures |
|:----------|:-----------------|
| `emit_zero_sub` | `emit()` on a type with a cached, empty chain |
| `emit_zero_sub_cold` | `emit()` where the chain must be (re)built every time |
| `emit_sync_1 / _10 / _100` | Sync dispatch with 1, 10, 100 handlers (loop scaling) |
| `emit_sync_context_1` | Sync dispatch with one context manager (`ExitStack` path) |
| `emit_async_sync_handlers_1 / _10` | Async dispatch of *sync* handlers (coroutine bridging) |
| `emit_async_async_handlers_1 / _10` | Async dispatch of async handlers |
| `emit_async_context_1` | Async dispatch with one async context manager |
| `inherited_dispatch` | Emit a grand-child event (merges two parent chains) |
| `chain_lookup` | `_get_chain()` alone, no dispatch |
| `add_subscriber`, `add_subscriber_10 / _100` | Subscription setup cost and its scaling |
| `async_baseline` | Reference: one batch of empty coroutines |

### Usage

```bash
# Everything (accurate; takes a few minutes)
poetry run python -m benchmark.profiling.micro -o profiling_results/baseline.json

# A subset
poetry run python -m benchmark.profiling.micro -b emit_sync_1 -b add_subscriber -o /tmp/subset.json

# Fast smoke run while iterating
poetry run python -m benchmark.profiling.micro --fast -p 1 -n 1 -w 1 -b emit_sync_1
```

Useful `pyperf` flags: `--rigorous` (more samples), `-p 1` (single worker, less jitter),
`-n` (values per worker), `-w` (warmups), `--quiet`, `--copy-env`.

### Reading the async numbers

Async benchmarks perform **`_ASYNC_BATCH` (1000) emits inside one `run_until_complete()`**
call, so the ~7 µs cost of entering the event loop is amortised instead of dominating the
measurement. **Divide the reported value by `_ASYNC_BATCH` to get the per-emit cost.**
`async_baseline` is the equivalent batch of empty coroutines and serves as the floor.

### Comparing a modified package

`micro.py` imports `eventlib` normally, so point `PYTHONPATH` at a patched copy:

```bash
# from a directory other than the repo root, so '' does not shadow PYTHONPATH
cd /tmp
PYTHONPATH=/path/to/patched python -m benchmark.profiling.micro -o /tmp/after.json
```

> **Gotcha:** running from the repository root puts `''` first on `sys.path`, which
> shadows `PYTHONPATH`. Verify with `python -c "import eventlib; print(eventlib.__file__)"`
> before trusting a comparison.

---

## `lines.py` — line-level attribution

`micro.py` tells you *how much*; `lines.py` tells you *which line*.

```bash
poetry run python -m benchmark.profiling.lines --list
poetry run python -m benchmark.profiling.lines sync_call
poetry run python -m benchmark.profiling.lines async_sync_handlers
poetry run python -m benchmark.profiling.lines subscribe
```

Available scenarios: `sync_call`, `sync_zero`, `sync_context`, `async_sync_handlers`,
`async_async_handlers`, `subscribe`, `chain_lookup`.

Only framework functions are instrumented (see `_TARGET_FUNCS`), so output stays focused.
Each scenario loops `LOOPS` (200 000) times to dominate profiler noise.

---

## `py-spy` — native sampling, zero code changes

Confirms that the tracing-based tools are not distorting the picture. Sampling happens in
a separate process, so overhead stays near zero.

```bash
VENV=$(poetry env info --path)

# Flamegraph (open the .svg in a browser)
"$VENV/bin/py-spy" record -o /tmp/spy.svg -r 500 -- "$VENV/bin/python" -m benchmark.profiling.lines sync_call

# speedscope / chrome-trace JSON for interactive exploration
"$VENV/bin/py-spy" record -f speedscope -o /tmp/spy.json -r 1000 -- "$VENV/bin/python" -m benchmark.profiling.lines sync_call
```

> **Gotcha:** invoke the `py-spy` **binary directly** and pass the interpreter explicitly.
> `poetry run py-spy record … -- python …` does not forward the options reliably, and
> `--format` is spelled `-f` in this version.
>
> On Linux, `kernel.yama.ptrace_scope` must allow tracing a child process (`1` is fine).

---

## `memray` — allocation attribution

Use when `tracemalloc` is too coarse: it names the exact allocation site for the
`ExitStack`, exception-list and coroutine objects created per emit.

```bash
poetry run memray run -o /tmp/mem.bin -m benchmark.profiling.lines chain_lookup
poetry run memray stats /tmp/mem.bin
poetry run memray flamegraph /tmp/mem.bin   # writes memray-flamegraph-*.html
```

---

## Analysis strategy

The workflow is deliberately layered: each layer answers a question the previous one
cannot, and each is cheap enough to re-run after every change.

### 1. Establish a baseline before touching code

Record `micro.py` output on the unmodified package and commit the JSON. Without a
baseline, "faster" is an opinion. Use the same machine, same interpreter and a quiet
system.

### 2. Isolate the framework from the workload

The end-to-end benchmark (`benchmark.py`) mixes handler cost with dispatch cost, which is
exactly what you want for a headline number and exactly what you *don't* want for
attribution. The `micro.py` scenarios deliberately use **no-op handlers** so that a
measured difference is attributable to the framework.

### 3. Follow the layers

| Layer | Tool | Question |
|:------|:-----|:---------|
| Macro | `pyperf` (`micro.py`) | Did it get faster, and by how much (± confidence)? |
| Function | `pyinstrument`, `cProfile` | Which function dominates? Are call counts inflated? |
| Line | `line_profiler` (`lines.py`) | Which line inside that function? |
| Allocation | `memray`, `tracemalloc` | How many objects per emit? Where are they created? |
| Validation | `py-spy` | Do the tracing tools agree with native sampling? |

`pyinstrument` is the preferred function-level profiler here because it is
**async-aware**: it attributes time inside `await` chains instead of blaming the event
loop. `cProfile` remains useful for its exact **call counts** — for example, proving that
a function is invoked twice per emit when it should be invoked once.

### 4. Verify with call counts, not just time

Timings say a path is slow; call counts say *why*. A function called `N × emits` times is
a strong signal of missing caching or a rebuild that should happen once.

### 5. Change one thing at a time

Measure each candidate fix in isolation, then cumulatively. If a fix shows no effect,
the hypothesis was wrong — investigate before layering more changes on top.

### 6. Prove behaviour is unchanged

Performance work in a library must not alter semantics. After every candidate change:

```bash
# from the repository root
poetry run pytest -q
```

All existing tests must pass. Pay particular attention to edge cases that a "fast path"
can silently break: empty collections, equal priorities, callables with unusual signatures
(classes, bound methods, `functools.wraps`-decorated wrappers, variadic `*args`).

### 7. Re-measure, then document the *numbers*

Re-run `micro.py`, compare with `pyperf compare_to`, and only then write down the result.
Record absolute values *and* the ratio, and note the interpreter and machine.

---

## Best practices

**Measurement hygiene**

- **Prefer `pyperf` over hand-rolled `perf_counter` loops.** It calibrates loop counts,
  detects outliers, reports confidence intervals, and its `compare_to` marks
  insignificant differences. A hand-rolled timer will happily report a 3 % "win" that is
  pure noise.
- **Separate warmup from measurement.** First-call costs (method caching, `inspect`
  machinery, JIT-like effects) are real but belong to *setup*, not steady-state dispatch.
  `micro.py` warms the chain before measuring and reports `add_subscriber` separately.
- **Never measure `asyncio.run()` or `run_until_complete()` per operation.** Loop entry
  costs several microseconds and will swamp a sub-microsecond dispatch. Batch operations
  inside one loop run (`_ASYNC_BATCH`) and state clearly what the reported unit is.
- **Beware `sys.path` shadowing.** `''` (the current directory) precedes `PYTHONPATH`, so
  running from the repo root silently ignores a patched copy. Always print
  `eventlib.__file__` when comparing variants.
- **Keep the machine quiet and pin workers.** Use `-p 1`, close background load, and
  compare runs made on the same machine and interpreter.
- **Beware micro-benchmarks that mutate state.** A benchmark that adds a subscriber to the
  *same* chain every call measures a growing chain, not the operation. Reset state inside
  the measured function (`clear_all_subscriptions()`) when that is the intent.
- **Check the tail, not just the mean.** `pyperf` reports quantiles; a change that helps
  the median but hurts p99 is not automatically a win.

**Profiling hygiene**

- **Use an async-aware profiler for async code.** `cProfile` cannot see inside `await`
  correctly; `pyinstrument` can.
- **Treat profiler overhead as a bias.** `cProfile` and `line_profiler` add per-call cost,
  which inflates functions with many small calls. Cross-check conclusions with `py-spy`.
- **Instrument narrowly.** Profiling every line of the standard library buries the signal.
  `lines.py` restricts itself to framework functions for this reason.
- **Distinguish tracing from sampling.** Tracing (cProfile, line_profiler) gives exact
  counts; sampling (pyinstrument, py-spy) gives representative time. Use each for what it
  is good at.

**Library-design hygiene**

- **Keep the public interface frozen.** Every optimisation here is internal. If a change
  would require a signature change, it is out of scope.
- **Preserve error semantics.** Exception grouping, `critical` short-circuiting and
  `asyncio.TimeoutError` handling are observable behaviour — fast paths must reproduce
  them exactly.
- **Cache what is provably immutable.** Parent-class resolution and handler kind are
  stable for the lifetime of a subscription; per-emit recomputation is pure waste.
- **Beware truthiness on collections.** A class defining `__len__` is falsy when empty, so
  `if obj := mapping.get(key):` treats a cached-but-empty chain as a cache miss and
  rebuilds it on every call. Prefer `if obj is not None:`.
- **Allocate nothing on the happy path.** `ExitStack()`, exception lists and coroutine
  objects created per emit are avoidable when no handler needs them.
- **Watch algorithmic complexity at setup.** Re-sorting the whole subscription list on
  every `add()` is O(n log n) per insert, i.e. O(n² log n) for n subscriptions; an in-place
  sorted insert is O(n) and the common append case is O(1).

---

## Tools & libraries

Installed via `poetry install --with=profiler` (see `[tool.poetry.group.profiler]` in
`pyproject.toml`). They are intentionally **not** dependencies of the library.

| Tool | Kind | Why it is here |
|:-----|:-----|:---------------|
| [`pyperf`](https://github.com/psf/pyperf) | Benchmark harness | Calibrated loops, outlier detection, confidence intervals, JSON results and `compare_to` for statistically defensible before/after claims. |
| [`pyinstrument`](https://github.com/joerick/pyinstrument) | Sampling profiler | Async-aware call-tree attribution; low overhead. Preferred function-level profiler for `emit_async`. |
| [`line_profiler`](https://github.com/pyutils/line_profiler) | Line profiler | Per-line timings inside the dispatch loops; the only way to prove *which statement* costs. |
| [`pytest-benchmark`](https://pytest-benchmark.readthedocs.io/) | Benchmark plugin | Turns a measurement into a repeatable test so a regression fails CI instead of going unnoticed. |
| [`py-spy`](https://github.com/benfred/py-spy) | Native sampling profiler | Out-of-process sampling with no code changes; validates that tracing profilers are not lying. Writes flamegraphs, speedscope and chrome-trace files. |
| [`memray`](https://github.com/bloomberg/memray) | Memory profiler | Allocator-level attribution of the objects created per emit; finer than `tracemalloc`. |
| [`viztracer`](https://github.com/alexmojaki/viztracer) | Timeline tracer | Visual timeline of async execution: coroutine creation, `await` gaps and exit-stack nesting. |

Standard-library tools used alongside them (no install required):

| Tool | Use |
|:-----|:----|
| `cProfile` + `pstats` | Exact call counts and cumulative time; the quickest way to spot call amplification. |
| `tracemalloc` | Object/allocation counts per emit when `memray` is unavailable. |
| `timeit` | Quick, isolated sanity checks of a single operation. |
| `dis` | Bytecode inspection to reason about the cost of a dispatch path. |

**Not usable in this environment:** Linux `perf` (`perf_event_paranoid = 2` blocks
counters without root). If you need it, lower the setting yourself — do not route
privileged commands through automation.

---

## Interpreting results responsibly

- Report **absolute values and the ratio**, plus the quantile you are quoting.
- State the **interpreter version** and the **machine**; both change the numbers.
- Distinguish **setup cost** (one-off, at subscription time) from **per-emit cost**
  (recurring). They matter for different workloads.
- A faster empty chain is not automatically a faster real system — confirm with the
  end-to-end benchmark in `benchmark/` that the headline overhead actually moved.
- If two tools disagree, believe the one with less overhead (`py-spy`), then explain the
  difference.
