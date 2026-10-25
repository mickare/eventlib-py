# Copyright 2026 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Micro-benchmarks for the eventlib dispatch path (pyperf).

Run with::

    poetry run python -m benchmark.profiling.micro -o baseline.json
    poetry run python -m benchmark.profiling.micro -o after.json
    poetry run python -m pyperf compare_to baseline.json after.json --table

Each benchmark isolates one dimension of the dispatch cost so handler cost does not
mask framework overhead. pyperf calibrates the loop count itself, so every benchmark
function here takes no arguments and performs exactly one emit (or one unit of work).

Note on the async benchmarks: each benchmark call performs ``_ASYNC_BATCH`` emits inside a
single ``run_until_complete`` call, so the ~7 us loop-entry cost is amortised instead of
dominating the result. Divide the reported value by ``_ASYNC_BATCH`` to get the per-emit
cost. ``async_baseline`` measures one batch of empty coroutines as the reference.
"""

import asyncio
import contextlib
import os
import sys
from typing import Any, Callable

import pyperf  # type: ignore[import-untyped]

from eventlib import Event, EventSystem

# pylint: disable=too-few-public-methods

BenchFunc = Callable[[], Any]

_ASYNC_BATCH = 1000
"""Number of emits performed inside one event-loop entry for the async benchmarks."""


# --------------------------------------------------------------------------------------------
# Event types
# --------------------------------------------------------------------------------------------
class Root(Event):
    """Event without event parents."""


class Child(Root):
    """Event with one event parent."""


class GrandChild(Child):
    """Event with two event parents."""


# --------------------------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------------------------
def sync_noop(_: Root) -> None:
    """Sync no-op handler."""


async def async_noop(_: Root) -> None:
    """Async no-op handler."""


@contextlib.contextmanager
def sync_cm(_: Root):
    """Sync context manager handler."""
    yield


@contextlib.asynccontextmanager
async def async_cm(_: Root):
    """Async context manager handler."""
    yield


def _make_sync_handlers(count: int) -> list[Callable[[Root], None]]:
    """Build `count` distinct sync no-op handlers."""
    handlers: list[Callable[[Root], None]] = []
    for index in range(count):
        def handler(_: Root) -> None:
            """Sync no-op handler."""

        handler.__name__ = f"sync_noop_{index}"
        handlers.append(handler)
    return handlers


# --------------------------------------------------------------------------------------------
# Shared async loop
# --------------------------------------------------------------------------------------------
_LOOP = asyncio.new_event_loop()


async def _async_noop_coro() -> None:
    """Trivial coroutine used to measure run_until_complete overhead."""


def _async_runner(system: EventSystem, event: Any) -> BenchFunc:
    """Return a zero-arg callable that emits `event` `_ASYNC_BATCH` times on the shared loop."""
    emit = system.emit_async
    run = _LOOP.run_until_complete

    async def batch() -> None:
        for _ in range(_ASYNC_BATCH):
            await emit(event)

    return lambda: run(batch())


# --------------------------------------------------------------------------------------------
# Benchmark factories
# --------------------------------------------------------------------------------------------
def bench_async_baseline() -> BenchFunc:
    """Baseline: `_ASYNC_BATCH` awaits of an empty coroutine."""
    run = _LOOP.run_until_complete

    async def batch() -> None:
        for _ in range(_ASYNC_BATCH):
            await _async_noop_coro()

    return lambda: run(batch())


def bench_emit_zero_sub() -> BenchFunc:
    """Emit an event whose chain exists but is empty (warm)."""
    system = EventSystem()
    event = Root()
    system.emit(event)  # create + cache the empty chain
    emit = system.emit
    return lambda: emit(event)


def bench_emit_zero_sub_cold() -> BenchFunc:
    """Emit an event whose chain must be rebuilt from scratch every time."""
    system = EventSystem()
    event = Root()
    emit = system.emit
    clear = system.clear_all_subscriptions

    def run() -> None:
        clear()
        emit(event)

    return run


def bench_emit_sync(n: int) -> BenchFunc:
    """Emit with `n` sync handlers."""
    system = EventSystem()
    for handler in _make_sync_handlers(n):
        system.subscribe()(handler)
    event = Root()
    system.emit(event)  # warm the cached dispatch methods
    emit = system.emit
    return lambda: emit(event)


def bench_emit_async_sync_handlers(n: int) -> BenchFunc:
    """Async emit with `n` sync handlers (measures coroutine bridging cost)."""
    system = EventSystem()
    for handler in _make_sync_handlers(n):
        system.subscribe()(handler)
    event = Root()
    _LOOP.run_until_complete(system.emit_async(event))  # warm
    return _async_runner(system, event)


def bench_emit_async_async_handlers(n: int) -> BenchFunc:
    """Async emit with `n` async handlers."""
    system = EventSystem()
    for _ in range(n):
        system.subscribe()(async_noop)
    event = Root()
    _LOOP.run_until_complete(system.emit_async(event))  # warm
    return _async_runner(system, event)


def bench_emit_sync_context() -> BenchFunc:
    """Sync emit with one sync context-manager handler (ExitStack cost)."""
    system = EventSystem()
    system.subscribe()(sync_cm)
    event = Root()
    system.emit(event)  # warm
    emit = system.emit
    return lambda: emit(event)


def bench_emit_async_context() -> BenchFunc:
    """Async emit with one async context-manager handler (AsyncExitStack cost)."""
    system = EventSystem()
    system.subscribe()(async_cm)
    event = Root()
    _LOOP.run_until_complete(system.emit_async(event))  # warm
    return _async_runner(system, event)


def bench_inherited_dispatch() -> BenchFunc:
    """Emit a grand-child event; the chain merges subscriptions of 2 parents."""
    system = EventSystem()
    system.subscribe()(sync_noop)
    system.subscribe(Root)(sync_noop)
    event = GrandChild()
    system.emit(event)
    emit = system.emit
    return lambda: emit(event)


def bench_chain_lookup() -> BenchFunc:
    """Measure only the chain lookup on an already-known type (no dispatch)."""
    system = EventSystem()
    system.subscribe()(sync_noop)
    event = Root()
    system.emit(event)
    get_chain = system._get_chain  # pylint: disable=protected-access
    event_type = type(event)
    return lambda: get_chain(event_type)


def bench_add_subscriber() -> BenchFunc:
    """Measure subscription setup cost for one subscriber on a fresh system."""
    system = EventSystem()
    subscribe = system.subscribe

    def run() -> None:
        system.clear_all_subscriptions()
        subscribe()(sync_noop)

    return run


def bench_add_subscriber_n(n: int) -> BenchFunc:
    """Measure adding `n` subscribers to the same chain (quadratic rebuild)."""
    handlers = _make_sync_handlers(n)

    def run() -> None:
        system = EventSystem()
        subscribe = system.subscribe
        for handler in handlers:
            subscribe()(handler)

    return run


# --------------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------------
BENCHMARKS: dict[str, Callable[[], BenchFunc]] = {
    "async_baseline": bench_async_baseline,
    "emit_zero_sub": bench_emit_zero_sub,
    "emit_zero_sub_cold": bench_emit_zero_sub_cold,
    "emit_sync_1": lambda: bench_emit_sync(1),
    "emit_sync_10": lambda: bench_emit_sync(10),
    "emit_sync_100": lambda: bench_emit_sync(100),
    "emit_async_sync_handlers_1": lambda: bench_emit_async_sync_handlers(1),
    "emit_async_sync_handlers_10": lambda: bench_emit_async_sync_handlers(10),
    "emit_async_async_handlers_1": lambda: bench_emit_async_async_handlers(1),
    "emit_async_async_handlers_10": lambda: bench_emit_async_async_handlers(10),
    "emit_sync_context_1": bench_emit_sync_context,
    "emit_async_context_1": bench_emit_async_context,
    "inherited_dispatch": bench_inherited_dispatch,
    "chain_lookup": bench_chain_lookup,
    "add_subscriber": bench_add_subscriber,
    "add_subscriber_10": lambda: bench_add_subscriber_n(10),
    "add_subscriber_100": lambda: bench_add_subscriber_n(100),
}


def _extract_selection(argv: list[str]) -> list[str] | None:
    """Pop `-b/--bench NAME` options before pyperf parses sys.argv."""
    selected: list[str] | None = None
    for flag in ("-b", "--bench"):
        while flag in argv:
            index = argv.index(flag)
            name = argv[index + 1]
            del argv[index : index + 2]
            selected = (selected or []) + [name]
    return selected


def main() -> None:
    """Run the selected benchmarks."""
    selected = _extract_selection(sys.argv)
    if selected:
        # pyperf re-spawns this script in a worker process per benchmark. The worker
        # re-runs main() with its own argv, so the selection is carried over in an
        # environment variable that pyperf must be told to inherit.
        os.environ["EVENTLIB_BENCH"] = ",".join(selected)
        if not any(arg.startswith("--inherit-environ") or arg == "--copy-env" for arg in sys.argv):
            sys.argv.append("--inherit-environ=EVENTLIB_BENCH")
    else:
        env_selection = os.environ.get("EVENTLIB_BENCH")
        selected = env_selection.split(",") if env_selection else None

    runner = pyperf.Runner()
    for name in selected or list(BENCHMARKS):
        if name not in BENCHMARKS:
            raise SystemExit(f"unknown benchmark {name!r}; choose from {', '.join(BENCHMARKS)}")
        runner.bench_func(name, BENCHMARKS[name]())


if __name__ == "__main__":
    main()
