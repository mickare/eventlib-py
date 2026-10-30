# Copyright 2026 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
End-to-end benchmark of a mixed sync/async dispatch.

This is the direct successor of the original benchmark: every kind of handler the library
supports is subscribed to the same event, so a single emit exercises the complete dispatch
machinery. The hand-written reference performs the same work without the event system.
"""

import asyncio
import contextlib

from eventlib import Event, EventSystem

from ..case import BenchFunc, Case

# pylint: disable=too-few-public-methods,unused-argument


class A(Event):
    """Base event of the case."""


class B(A):
    """Emitted event of the case."""


def sync_func0(_: A) -> None:
    """Sync handler for A."""


def sync_func1(_: B) -> None:
    """Sync handler for B."""


async def async_func(_: B) -> None:
    """Async handler for B."""
    await asyncio.sleep(0)


@contextlib.contextmanager
def sync_context_func(_: B):
    """Sync context manager handler for B."""
    yield


@contextlib.asynccontextmanager
async def async_context_func(_: B):
    """Async context manager handler for B."""
    await asyncio.sleep(0)
    yield
    await asyncio.sleep(0)


class SyncContextClass:
    """Sync context manager handler class for B."""

    def __init__(self, _: B) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return None


class AsyncContextClass:
    """Async context manager handler class for B."""

    def __init__(self, _: B) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


def _build_system() -> EventSystem:
    """Create a system with one handler of every supported kind."""
    system = EventSystem()
    system.subscribe(priority=-2)(async_context_func)
    system.subscribe(priority=-2)(AsyncContextClass)

    system.subscribe(priority=-1)(sync_context_func)
    system.subscribe(priority=-1)(SyncContextClass)

    system.subscribe(priority=0)(sync_func0)
    system.subscribe(priority=1)(sync_func1)
    system.subscribe(priority=2)(async_func)
    return system


def _reference() -> BenchFunc:
    """Hand-written equivalent of one emit."""

    async def run() -> None:
        async with async_context_func(EVENT), AsyncContextClass(EVENT):
            with sync_context_func(EVENT), SyncContextClass(EVENT):
                sync_func0(EVENT)
                sync_func1(EVENT)
                await async_func(EVENT)

    return run


def _library() -> BenchFunc:
    """One emit through the event system."""
    system = _build_system()
    asyncio.run(system.emit_async(EVENT))  # warm the cached chains and call methods

    async def run() -> None:
        await system.emit_async(EVENT)

    return run


EVENT = B()
"""Event instance emitted by every iteration."""


CASES = (
    Case(
        name="mixed_sync_async",
        group="macro",
        description="One emit with 2 async CM, 2 sync CM, 2 sync and 1 async handler",
        reference=_reference,
        library=_library,
        is_async=True,
    ),
)
