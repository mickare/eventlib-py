# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

# pylint: disable=duplicate-code
"""
Example of receiving events, validating them with Pydantic and handling with eventlib-py library.
See more: https://pypi.org/project/pydantic/

Requirements:
  - pydantic
"""
from datetime import datetime
from typing import Annotated, Iterator, Literal

from pydantic import BaseModel, Field, TypeAdapter

from eventlib import BaseEvent, emit, subscribe


class ItemEvent(BaseEvent, BaseModel):
    """A generic item event."""

    type: str
    timestamp: datetime


class CreatedItemEvent(ItemEvent):
    """Example event for a created item."""

    type: Literal["created"]
    name: str
    value: int


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
AnyEvent = Annotated[CreatedItemEvent | DeletedItemEvent, Field(discriminator="type")]
AnyEventAdapter: TypeAdapter[AnyEvent] = TypeAdapter(AnyEvent)


def receive() -> Iterator[AnyEvent]:
    """Dummy receive method. This could be a Kafka, ServiceBus, RabbitMQ, or any other event receiver."""
    for raw in EXAMPLE_EVENTS:
        yield AnyEventAdapter.validate_python(raw)


def example_pydantic():
    """Example to validate, parse and emit an event using pydantic and the eventlib-py library."""
    for event in receive():
        emit(event)


if __name__ == "__main__":
    example_pydantic()
