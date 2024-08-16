# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

# pylint: disable=duplicate-code
"""
Example of receiving events defined with attrs and handling with eventlib-py library.
See more: https://pypi.org/project/attrs/

Requirements:
  - attrs
"""
from datetime import datetime
from typing import Iterator, Literal

from attrs import define

from eventlib import BaseEvent, emit, subscribe


@define
class ItemEvent(BaseEvent):
    """A generic item event."""

    type: str
    timestamp: datetime


@define
class CreatedItemEvent(ItemEvent):
    """Example event for a created item."""

    type: Literal["created"]
    name: str
    value: int


@define
class DeletedItemEvent(ItemEvent):
    """Example event for a deleted item."""

    type: Literal["deleted"]
    name: str


@subscribe()
def on_created(event: CreatedItemEvent):
    """Handle created events"""
    print("on_created:", repr(event))


@subscribe()
def on_deleted(event: DeletedItemEvent):
    """Handle deleted events"""
    print("on_deleted:", repr(event))


EXAMPLE_EVENTS: list[dict] = [
    {"type": "created", "timestamp": "2024-08-16T20:00:00", "name": "event_1", "value": 1},
    {"type": "created", "timestamp": "2024-08-16T20:01:00", "name": "event_2", "value": 2},
    {"type": "deleted", "timestamp": "2024-08-16T20:02:00", "name": "event_1"},
]
AnyEvent = CreatedItemEvent | DeletedItemEvent


def receive() -> Iterator[AnyEvent]:
    """Dummy receive method. This could be a Kafka, ServiceBus, RabbitMQ, or any other event receiver."""
    for raw in EXAMPLE_EVENTS:
        match raw["type"]:
            case "created":
                yield CreatedItemEvent(**raw)
            case "deleted":
                yield DeletedItemEvent(**raw)
            case _:
                raise RuntimeError("unknown event")


def example_attrs():
    """Example to an event using attrs and the eventlib-py library."""
    for event in receive():
        emit(event)


if __name__ == "__main__":
    example_attrs()
