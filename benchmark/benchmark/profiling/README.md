# Profiling & Performance Analysis

Tooling to *attribute* the runtime cost of `eventlib-py` to functions, lines and
allocations.

This directory answers a different question than the benchmark suite next to it:

| Question | Tool |
|:---------|:-----|
| *How much* does the framework cost, and is it faster than before? | `python -m benchmark` (pyperf suite) |
| *Where inside the library* does the time go? | this directory |

---

## Contents

| File | Purpose |
|:-----|:--------|
| `lines.py` | `line_profiler` scenarios. Attributes cost to individual **lines** inside `EventChain.call`, `call_async`, `_get_chain`, `add_subscriber`, … |
| `results/` | Baseline and candidate result files (`*.json`) written by the benchmark suite. |

> The former `micro.py` lived here. It duplicated the `micro` group of the main suite and
> has been removed — run `python -m benchmark run --select micro` instead. The suite writes
> pyperf-compatible results, so `pyperf compare_to` works on them exactly as it did before.

---

## Setup

The profilers live in the `profiler` dependency group so the library itself keeps its
"no runtime dependencies" property:

```bash
cd benchmark
poetry install --with=profiler
```

---

## Benchmark first, profile second

Always start with the suite. It tells you *whether* a change helped, with confidence
intervals, before you spend time on attribution.

```bash
cd benchmark

# 1. Record a baseline (writes results/baseline.json)
poetry run benchmark run --summary results/baseline.json

# 2. Change something, record again
poetry run benchmark run --summary results/after.json

# 3. Compare the two reports side by side
poetry run benchmark render --summary results/baseline.json -o results/baseline.png
poetry run benchmark render --summary results/after.json -o results/after.png
```

Each report prints the per-case ratios and the overall score, so the two runs can be read
off directly. For a statistical before/after test, keep pyperf's native output
(`-o FILE`) and use `python -m pyperf compare_to`.

### Filtering

`--select` accepts a group (`macro`, `micro`, `journey`), a full case id
(`micro.emit_sync_10`) or a bare case name (`emit_sync_10`), and can be repeated:

```bash
poetry run benchmark run --select micro --fast --quiet
poetry run benchmark run --select micro.emit_sync_1 --select micro.subscribe_1
```

### pyperf flags

Every option the suite does not recognise is forwarded to pyperf, so the standard knobs
work unchanged:

```bash
poetry run benchmark run --fast                 # quick smoke run
poetry run benchmark run --rigorous             # more samples
poetry run benchmark run -p 1 -n 5              # pin workers / values per worker
poetry run benchmark run --affinity 2-3         # pin to specific CPUs
```

Because pyperf re-spawns the interpreter for every benchmark, run with `-O` to disable
assertions (the library has `assert_not_*` helpers that are active under `__debug__`):

```bash
poetry run python -O -m benchmark run --summary results/baseline-o.json
```

The suite forwards the interpreter's optimisation flags to its worker processes.

---

## `lines.py` — line-level attribution

The suite tells you *how much*; `lines.py` tells you *which line*.

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

Confirms that the tracing-based tools are not distorting the picture. Sampling happens in a
separate process, so overhead stays near zero.

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

## `pyinstrument` — async-aware function profiling

`cProfile` cannot see inside `await` correctly; `pyinstrument` can.

```bash
poetry run pyinstrument -m benchmark.profiling.lines async_async_handlers
```

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

Record the suite output on the unmodified package and commit the summary. Without a
baseline, "faster" is an opinion. Use the same machine, same interpreter and a quiet
system.

### 2. Isolate the framework from the workload

The `macro` and `journey` groups mix handler cost with dispatch cost, which is exactly what
you want for a headline number and exactly what you *don't* want for attribution. The
`micro` group deliberately uses **no-op handlers** so a measured difference is attributable
to the framework.

### 3. Follow the layers

| Layer | Tool | Question |
|:------|:-----|:---------|
| Macro | `pyperf` (`benchmark run`) | Did it get faster, and by how much (± confidence)? |
| Function | `pyinstrument`, `cProfile` | Which function dominates? Are call counts inflated? |
| Line | `line_profiler` (`lines.py`) | Which line inside that function? |
| Allocation | `memray`, `tracemalloc` | How many objects per emit? Where are they created? |
| Validation | `py-spy` | Do the tracing tools agree with native sampling? |

### 4. Verify with call counts, not just time

Timings say a path is slow; call counts say *why*. A function called `N × emits` times is a
strong signal of missing caching or a rebuild that should happen once.

### 5. Change one thing at a time

Measure each candidate fix in isolation, then cumulatively. If a fix shows no effect, the
hypothesis was wrong — investigate before layering more changes on top.

### 6. Prove behaviour is unchanged

Performance work in a library must not alter semantics. After every candidate change:

```bash
# from the repository root
poetry run pytest -q
```

All existing tests must pass. Pay particular attention to edge cases that a "fast path" can
silently break: empty collections, equal priorities, callables with unusual signatures
(classes, bound methods, `functools.wraps`-decorated wrappers, variadic `*args`).

### 7. Re-measure, then document the *numbers*

Re-run the suite, compare the two reports, and only then write down the result. Record
absolute values *and* the ratio, and note the interpreter and machine.

---

## Best practices

**Measurement hygiene**

- **Prefer `pyperf` over hand-rolled `perf_counter` loops.** It calibrates loop counts,
  detects outliers, reports confidence intervals, and `compare_to` marks insignificant
  differences. A hand-rolled timer will happily report a 3 % "win" that is pure noise.
- **Separate warmup from measurement.** First-call costs (method caching, `inspect`
  machinery) are real but belong to *setup*, not steady-state dispatch. Every case warms
  its chain before measuring; `subscribe_*` measures setup deliberately.
- **Never measure `asyncio.run()` per operation.** Loop entry costs several microseconds
  and will swamp a sub-microsecond dispatch. Async cases use pyperf's
  `bench_async_func`, which enters the loop once per calibrated batch and reports the
  per-operation cost.
- **Use the median, not the mean.** pyperf reports outliers (scheduler noise, GC pauses).
  The suite uses the median of each series and the median of the per-case ratios, so a
  single noisy sample cannot move the headline number.
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
  sorted insert is O(n) and the common append case is O(1). The `subscribe_100` case exists
  to keep that visible.

---

## Tools & libraries

Installed via `poetry install --with=profiler` (see `[tool.poetry.group.profiler]` in
`pyproject.toml`). They are intentionally **not** dependencies of the library.

| Tool | Kind | Why it is here |
|:-----|:-----|:---------------|
| [`pyperf`](https://github.com/psf/pyperf) | Benchmark harness | Calibrated loops, outlier detection, confidence intervals, JSON results and `compare_to` for statistically defensible before/after claims. |
| [`pyinstrument`](https://github.com/joerick/pyinstrument) | Sampling profiler | Async-aware call-tree attribution; low overhead. Preferred function-level profiler for `emit_async`. |
| [`line_profiler`](https://github.com/pyutils/line_profiler) | Line profiler | Per-line timings inside the dispatch loops; the only way to prove *which statement* costs. |
| [`py-spy`](https://github.com/benfred/py-spy) | Native sampler | Independent validation that the tracing tools are not distorting the picture. |
| [`memray`](https://github.com/bloomberg/memray) | Allocation profiler | Names the allocation site of the objects created per emit. |
