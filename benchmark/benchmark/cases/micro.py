# Copyright 2026 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Micro-benchmarks of the dispatch path.

Each case isolates **one** dimension of the framework cost (handler count, sync vs async,
context managers, inheritance, subscription setup). Handlers are no-ops, so a measured
difference is attributable to the framework and not to user code.

Every case also has a hand-written reference that performs the same minimal work, which
makes the reported ratio meaningful: it is the factor the framework adds on top of the
plain Python equivalent.

Async cases are measured with ``Runner.bench_async_func``: pyperf enters the event loop
once and then awaits the coroutine for the calibrated number of loops, so the ~7 µs cost
of loop entry is amortised instead of dominating a sub-microsecond dispatch.
"""

import asyncio
import bisect
import contextlib
from typing import Any, Callable

from eventlib import Event, EventSystem

from ..case import BenchFunc, Case

# pylint: disable=too-few-public-methods,unused-argument


# --------------------------------------------------------------------------------------------
# Event types
# --------------------------------------------------------------------------------------------
class Root(Event):
    """Event without event parents."""


class Child(Root):
    """Event with one event parent."""


class GrandChild(Child):
    """Event with two event parents."""


EVENT = Root()
"""Event instance emitted by the micro-benchmarks."""


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


def make_sync_handlers(count: int) -> tuple[Callable[[Root], None], ...]:
    """Build `count` distinct sync no-op handlers."""

    def make(index: int) -> Callable[[Root], None]:
        def handler(_: Root) -> None:
            """Sync no-op handler."""

        handler.__name__ = f"sync_noop_{index}"
        return handler

    return tuple(make(index) for index in range(count))


def make_async_handlers(count: int) -> tuple[Callable[[Root], Any], ...]:
    """Build `count` distinct async no-op handlers."""

    def make(index: int) -> Callable[[Root], Any]:
        async def handler(_: Root) -> None:
            """Async no-op handler."""

        handler.__name__ = f"async_noop_{index}"
        return handler

    return tuple(make(index) for index in range(count))


def build_system(*handlers: Callable[..., Any]) -> EventSystem:
    """Create an event system with the given handlers subscribed to `Root`."""
    system = EventSystem()
    for handler in handlers:
        system.subscribe(Root)(handler)
    return system


# --------------------------------------------------------------------------------------------
# Factories: sync dispatch
# --------------------------------------------------------------------------------------------
def _emit_sync(count: int) -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair for `count` sync handlers."""
    handlers = make_sync_handlers(count)

    def reference() -> None:
        for handler in handlers:
            handler(EVENT)

    system = build_system(*handlers)
    system.emit(EVENT)  # warm the cached chain and call methods
    emit = system.emit

    def library() -> None:
        emit(EVENT)

    return reference, library


def _emit_sync_context() -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair for a single sync context manager handler."""

    def reference() -> None:
        with sync_cm(EVENT):
            pass

    system = build_system(sync_cm)
    system.emit(EVENT)  # warm
    emit = system.emit

    def library() -> None:
        emit(EVENT)

    return reference, library


def _emit_zero_sub() -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair for an event whose chain is cached and empty."""

    def reference() -> None:
        pass

    system = EventSystem()
    system.emit(EVENT)  # create and cache the empty chain
    emit = system.emit

    def library() -> None:
        emit(EVENT)

    return reference, library


def _emit_zero_sub_cold() -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair where the chain must be rebuilt on every emit.

    The reference only repeats the unavoidable cache bookkeeping, so the ratio is
    indicative rather than a like-for-like comparison.
    """
    cache: dict[type[Event], list[Any]] = {}

    def reference() -> None:
        cache.clear()
        cache[Root] = []

    system = EventSystem()
    system.emit(EVENT)  # warm the type checks
    emit = system.emit
    clear = system.clear_all_subscriptions

    def library() -> None:
        clear()
        emit(EVENT)

    return reference, library


def _inherited_dispatch() -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair for an event with two event parents."""

    def on_root(_: Root) -> None:
        """Handler on the root event."""

    def on_child(_: Child) -> None:
        """Handler on the child event."""

    def on_grand_child(_: GrandChild) -> None:
        """Handler on the grand-child event."""

    event = GrandChild()

    def reference() -> None:
        on_root(event)
        on_child(event)
        on_grand_child(event)

    system = EventSystem()
    system.subscribe(Root)(on_root)
    system.subscribe(Child)(on_child)
    system.subscribe(GrandChild)(on_grand_child)
    system.emit(event)  # warm
    emit = system.emit

    def library() -> None:
        emit(event)

    return reference, library


# --------------------------------------------------------------------------------------------
# Factories: async dispatch
# --------------------------------------------------------------------------------------------
def _emit_async_sync_handlers(count: int) -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair for async dispatch of `count` sync handlers."""
    handlers = make_sync_handlers(count)

    async def reference() -> None:
        for handler in handlers:
            handler(EVENT)

    system = build_system(*handlers)
    asyncio.run(system.emit_async(EVENT))  # warm
    emit = system.emit_async

    async def library() -> None:
        await emit(EVENT)

    return reference, library


def _emit_async_async_handlers(count: int) -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair for async dispatch of `count` async handlers."""
    handlers = make_async_handlers(count)

    async def reference() -> None:
        for handler in handlers:
            await handler(EVENT)

    system = build_system(*handlers)
    asyncio.run(system.emit_async(EVENT))  # warm
    emit = system.emit_async

    async def library() -> None:
        await emit(EVENT)

    return reference, library


def _emit_async_context() -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair for a single async context manager handler."""

    async def reference() -> None:
        async with async_cm(EVENT):
            pass

    system = build_system(async_cm)
    asyncio.run(system.emit_async(EVENT))  # warm
    emit = system.emit_async

    async def library() -> None:
        await emit(EVENT)

    return reference, library


# --------------------------------------------------------------------------------------------
# Factories: subscription setup
# --------------------------------------------------------------------------------------------
def _subscribe(count: int) -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair for registering `count` handlers.

    The reference performs the same data-structure operation the library performs -
    a priority-ordered insert into a list - but without the framework's signature
    inspection, metadata and chain bookkeeping. The ratio is therefore the cost of that
    bookkeeping, not of the insert itself.
    """
    handlers = make_sync_handlers(count)
    target: list[tuple[int, Callable[[Root], None]]] = []

    def reference() -> None:
        target.clear()
        for handler in handlers:
            bisect.insort(target, (0, handler), key=lambda item: item[0])

    system = EventSystem()
    subscribe = system.subscribe
    clear = system.clear_all_subscriptions

    def library() -> None:
        clear()
        for handler in handlers:
            subscribe(Root)(handler)

    return reference, library


# --------------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------------
CASES = (
    Case(
        name="emit_sync_1",
        group="micro",
        description="Sync emit with 1 no-op handler",
        reference=lambda: _emit_sync(1)[0],
        library=lambda: _emit_sync(1)[1],
    ),
    Case(
        name="emit_sync_10",
        group="micro",
        description="Sync emit with 10 no-op handlers",
        reference=lambda: _emit_sync(10)[0],
        library=lambda: _emit_sync(10)[1],
    ),
    Case(
        name="emit_sync_100",
        group="micro",
        description="Sync emit with 100 no-op handlers",
        reference=lambda: _emit_sync(100)[0],
        library=lambda: _emit_sync(100)[1],
    ),
    Case(
        name="emit_async_sync_1",
        group="micro",
        description="Async emit with 1 sync no-op handler",
        reference=lambda: _emit_async_sync_handlers(1)[0],
        library=lambda: _emit_async_sync_handlers(1)[1],
        is_async=True,
    ),
    Case(
        name="emit_async_sync_10",
        group="micro",
        description="Async emit with 10 sync no-op handlers",
        reference=lambda: _emit_async_sync_handlers(10)[0],
        library=lambda: _emit_async_sync_handlers(10)[1],
        is_async=True,
    ),
    Case(
        name="emit_async_async_1",
        group="micro",
        description="Async emit with 1 async no-op handler",
        reference=lambda: _emit_async_async_handlers(1)[0],
        library=lambda: _emit_async_async_handlers(1)[1],
        is_async=True,
    ),
    Case(
        name="emit_async_async_10",
        group="micro",
        description="Async emit with 10 async no-op handlers",
        reference=lambda: _emit_async_async_handlers(10)[0],
        library=lambda: _emit_async_async_handlers(10)[1],
        is_async=True,
    ),
    Case(
        name="emit_sync_context",
        group="micro",
        description="Sync emit with 1 sync context manager handler",
        reference=lambda: _emit_sync_context()[0],
        library=lambda: _emit_sync_context()[1],
    ),
    Case(
        name="emit_async_context",
        group="micro",
        description="Async emit with 1 async context manager handler",
        reference=lambda: _emit_async_context()[0],
        library=lambda: _emit_async_context()[1],
        is_async=True,
    ),
    Case(
        name="inherited_dispatch",
        group="micro",
        description="Emit a grand-child event, merging two parent chains",
        reference=lambda: _inherited_dispatch()[0],
        library=lambda: _inherited_dispatch()[1],
    ),
    Case(
        name="emit_zero_sub",
        group="micro",
        description="Sync emit with a cached but empty chain (framework floor)",
        reference=lambda: _emit_zero_sub()[0],
        library=lambda: _emit_zero_sub()[1],
        scored=False,
    ),
    Case(
        name="emit_zero_sub_cold",
        group="micro",
        description="Sync emit where the empty chain must be rebuilt each time",
        reference=lambda: _emit_zero_sub_cold()[0],
        library=lambda: _emit_zero_sub_cold()[1],
        scored=False,
    ),
    Case(
        name="subscribe_1",
        group="micro",
        description="Register 1 handler on a fresh chain",
        reference=lambda: _subscribe(1)[0],
        library=lambda: _subscribe(1)[1],
    ),
    Case(
        name="subscribe_10",
        group="micro",
        description="Register 10 handlers on a fresh chain",
        reference=lambda: _subscribe(10)[0],
        library=lambda: _subscribe(10)[1],
    ),
    Case(
        name="subscribe_100",
        group="micro",
        description="Register 100 handlers on a fresh chain",
        reference=lambda: _subscribe(100)[0],
        library=lambda: _subscribe(100)[1],
    ),
)
