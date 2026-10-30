# Copyright 2026 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Line-level profiling of the eventlib dispatch path.

Usage::

    poetry run python -m benchmark.profiling.lines --list
    poetry run python -m benchmark.profiling.lines sync_call

Each profile drives a tight loop over a single dispatch scenario so that the reported
per-line timings are dominated by framework code rather than by the handlers.
"""

import asyncio
import contextlib
import sys

from eventlib import Event, EventSystem
from eventlib.core import EventChain, EventSub
from line_profiler import LineProfiler

# pylint: disable=too-few-public-methods,protected-access

LOOPS = 200_000
"""Iterations per profile. High enough to dominate profiler noise."""


class Root(Event):
    """Event without parents."""


def sync_noop(_: Root) -> None:
    """Sync no-op handler."""


async def async_noop(_: Root) -> None:
    """Async no-op handler."""


@contextlib.contextmanager
def sync_cm(_: Root):
    """Sync context manager."""
    yield


@contextlib.asynccontextmanager
async def async_cm(_: Root):
    """Async context manager."""
    yield


def _system_with(*handlers) -> EventSystem:
    """Build an event system with the given handlers subscribed."""
    system = EventSystem()
    for handler in handlers:
        system.subscribe()(handler)
    return system


def profile_sync_call() -> None:
    """EventChain.call with 10 sync handlers."""
    system = _system_with(*([sync_noop] * 10))
    event = Root()
    system.emit(event)  # warm
    for _ in range(LOOPS):
        system.emit(event)


def profile_sync_zero() -> None:
    """EventSystem.emit with a cached, empty chain."""
    system = EventSystem()
    event = Root()
    system.emit(event)  # create the empty chain
    for _ in range(LOOPS):
        system.emit(event)


def profile_sync_context() -> None:
    """EventChain.call with a sync context manager (ExitStack path)."""
    system = _system_with(sync_cm)
    event = Root()
    system.emit(event)  # warm
    for _ in range(LOOPS):
        system.emit(event)


def profile_async_sync_handlers() -> None:
    """EventChain.call_async with 10 sync handlers (coroutine bridging path)."""
    system = _system_with(*([sync_noop] * 10))
    event = Root()
    loop = asyncio.new_event_loop()

    async def run(n: int) -> None:
        emit = system.emit_async
        for _ in range(n):
            await emit(event)

    loop.run_until_complete(run(100))  # warm
    loop.run_until_complete(run(LOOPS))


def profile_async_async_handlers() -> None:
    """EventChain.call_async with 10 async handlers."""
    system = _system_with(*([async_noop] * 10))
    event = Root()
    loop = asyncio.new_event_loop()

    async def run(n: int) -> None:
        emit = system.emit_async
        for _ in range(n):
            await emit(event)

    loop.run_until_complete(run(100))  # warm
    loop.run_until_complete(run(LOOPS))


def profile_subscribe() -> None:
    """EventSystem.add_subscriber / EventChain.add."""
    for _ in range(LOOPS // 20):
        system = EventSystem()
        system.subscribe()(sync_noop)


def profile_chain_lookup() -> None:
    """EventSystem._get_chain on an already-known type."""
    system = _system_with(sync_noop)
    event = Root()
    system.emit(event)
    get_chain = system._get_chain  # pylint: disable=protected-access
    for _ in range(LOOPS):
        get_chain(type(event))


PROFILES = {
    "sync_call": profile_sync_call,
    "sync_zero": profile_sync_zero,
    "sync_context": profile_sync_context,
    "async_sync_handlers": profile_async_sync_handlers,
    "async_async_handlers": profile_async_async_handlers,
    "subscribe": profile_subscribe,
    "chain_lookup": profile_chain_lookup,
}
"""Named profiling scenarios."""

# Only report lines from the framework itself.
_TARGET_FUNCS = [
    EventSystem.emit,
    EventSystem.emit_async,
    EventSystem._get_chain,
    EventSystem.add_subscriber,
    EventChain.call,
    EventChain.call_async,
    EventChain.add,
    EventChain.__init__,
    EventSub.__init__,
    EventSub._call,
    EventSub._acall,
]


def main() -> None:
    """Run one profiling scenario."""
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "--list"):
        print(__doc__)
        print("Available profiles:")
        for name, func in PROFILES.items():
            print(f"  {name:<22} {func.__doc__}")
        return

    name = sys.argv[1]
    if name not in PROFILES:
        raise SystemExit(f"unknown profile {name!r}; choose from {', '.join(PROFILES)}")

    profiler = LineProfiler(*_TARGET_FUNCS)
    profiler.runcall(PROFILES[name])
    profiler.print_stats(output_unit=1e-6)


if __name__ == "__main__":
    main()
