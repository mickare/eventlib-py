# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Example of using an `asyncio.Queue` and workers to schedule and emit events.
"""


import asyncio
import dataclasses

from eventlib import BaseEvent

queue: asyncio.Queue[BaseEvent] = asyncio.Queue()


# ==================================================================================================
# Events
@dataclasses.dataclass
class MoreWorkEvents(BaseEvent):
    """Schedule more events to the queue."""

    events: list[BaseEvent]


@dataclasses.dataclass
class PrintEvent(BaseEvent):
    """Prints a message."""

    message: str


# ==================================================================================================
# Event handler
@MoreWorkEvents.subscribe()
async def schedule_more(event: MoreWorkEvents):
    """Schedule more events to the queue."""
    for e in event.events:
        await queue.put(e)


@PrintEvent.subscribe()
def print_message(event: PrintEvent):
    """Prints the message of the event."""
    print(event.message)


# ==================================================================================================
# Event worker
async def worker(wid: int):
    """Worker that consumes events from the queue and emits it."""
    while True:
        event: BaseEvent = await queue.get()
        try:
            print(f"Worker {wid}: Working on {event}")
            await event.emit_async()
            print(f"Worker {wid}: Finished {event}")
        finally:
            queue.task_done()


# ==================================================================================================
# Example
async def worker_example(worker_count: int = 10):
    """Example of a worker queue that emits events"""
    queue.put_nowait(
        MoreWorkEvents(
            events=[
                PrintEvent(message="Hello"),
                PrintEvent(message="World"),
            ]
        )
    )
    queue.put_nowait(PrintEvent(message="Goodbye"))

    async with asyncio.TaskGroup() as tg:
        # Startup
        workers = [tg.create_task(worker(wid)) for wid in range(worker_count)]
        # Wait for all events to be consumed
        await tg.create_task(queue.join())
        # Shutdown
        for task in workers:
            task.cancel()


if __name__ == "__main__":
    asyncio.run(worker_example())
