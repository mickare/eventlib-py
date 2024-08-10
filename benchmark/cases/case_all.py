# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Benchmark of a mixed use-case with all kinds of sync & async event functions and context managers.

The reference implementation is the following::

    async def run_reference(event: B):
        async with async_context_func(event), AsyncContextClass(event):
            with sync_context_func(event), SyncContextClass(event):
                sync_func0(event)
                sync_func1(event)
                await async_func(event)
"""

import asyncio
import contextlib

from eventlib import Event, EventSystem


# pylint: disable=too-few-public-methods
class A(Event):
    """Test event class"""


# pylint: disable=too-few-public-methods
class B(A):
    """Test event class"""


def sync_func0(_: A):
    """Sync event handler for A"""


def sync_func1(_: B):
    """Sync event handler for B"""


async def async_func(_: B):
    """Async event handler for B"""
    await asyncio.sleep(0)


@contextlib.contextmanager
def sync_context_func(_: B):
    """Sync context handler for B"""
    yield


@contextlib.asynccontextmanager
async def async_context_func(_: B):
    """Async context handler for B"""
    await asyncio.sleep(0)
    yield
    await asyncio.sleep(0)


class SyncContextClass:
    """Sync context handler class for B"""

    def __init__(self, _: B):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class AsyncContextClass:
    """Async context handler class for B"""

    def __init__(self, _: B):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


def build(system: EventSystem) -> None:
    """Prepare the event system."""
    system.subscribe(priority=-2)(async_context_func)
    system.subscribe(priority=-2)(AsyncContextClass)

    system.subscribe(priority=-1)(sync_context_func)
    system.subscribe(priority=-1)(SyncContextClass)

    system.subscribe(priority=0)(sync_func0)
    system.subscribe(priority=1)(sync_func1)
    system.subscribe(priority=2)(async_func)


def new_event() -> Event:
    """Get the event."""
    return B()


async def run_reference(event: B) -> None:
    """Run the reference implementation."""
    async with async_context_func(event), AsyncContextClass(event):
        with sync_context_func(event), SyncContextClass(event):
            sync_func0(event)
            sync_func1(event)
            await async_func(event)


async def run_eventlib(system: EventSystem, event: B) -> None:
    """Run the eventlib implementation."""
    await system.emit_async(event)
