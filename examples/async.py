# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

# pylint: disable=unused-argument
"""
Example of using async handlers.
"""

import asyncio
import contextlib

import eventlib


class MyEvent(eventlib.BaseEvent):
    """Some event"""


@eventlib.subscribe(priority=-1000)  # Ensure that this is called first
@contextlib.asynccontextmanager
async def monitor(event: MyEvent):
    """Async enter the context with the event"""
    print("Event received")
    try:
        yield
    finally:
        print("Event processed")


@eventlib.subscribe()
async def async_on_event(event: MyEvent):
    """Async handle the event"""
    print("async_on_event")


@eventlib.subscribe()
def on_event(event: MyEvent):
    """Synchronously handle the event"""
    print("on_event")


# ==================================================================================================
# Example
async def async_example():
    """
    Emits a single event and calls all subscribers.
    """
    await MyEvent().emit_async()


if __name__ == "__main__":
    asyncio.run(async_example())
