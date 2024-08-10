# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Base classes for the easy integration into the "global" singleton event system.

You can use the method `set_default_event_system()` to set your own event system as the default one.
"""

from typing import ClassVar, Self, TypeVar

from eventlib.core import Event, EventHandler, EventHandlerDecorator, EventSystem

E = TypeVar("E", bound=Event)
BASE_EVENT_SYSTEM = EventSystem()
"""The global event system."""


class BaseEvent(Event):
    """Event class that can be extended to create custom events. Use this for the global event system."""

    event_system: ClassVar[EventSystem]

    @classmethod
    def __init_subclass__(cls, /, event_system: EventSystem | None = None, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        parent_event0 = [base for base in cls.__bases__ if issubclass(base, BaseEvent)][0]
        cls.event_system = (
            event_system or getattr(cls, "event_system", None) or parent_event0.event_system or BASE_EVENT_SYSTEM
        )

    @classmethod
    def subscribe(cls, priority: int = 0, critical: bool = False) -> EventHandlerDecorator[Self]:
        """Subscribe to this event."""
        return cls.event_system.subscribe(cls, priority=priority, critical=critical)

    @classmethod
    def unsubscribe(cls, func: EventHandler[Self]):
        """Unsubscribe from this event."""
        cls.event_system.unsubscribe(func)

    @classmethod
    def unsubscribe_all(cls):
        """Unsubscribe all event handlers from this event."""
        cls.event_system.unsubscribe_all(cls)

    def emit(self) -> Self:
        """Emit this event."""
        self.event_system.emit(self)
        return self

    async def emit_async(self) -> Self:
        """Emit this event asynchronously."""
        await self.event_system.emit_async(self)
        return self


# Set the default event system for the BaseEvent class
BaseEvent.event_system = BASE_EVENT_SYSTEM


# pylint: disable=global-statement
def set_event_system(event_system: EventSystem):
    """
    Set the global event system for the BaseEvent class.

    This will not preserve any existing event system used by the BaseEvent class or derivatives.
    Make sure to call this method before importing any modules that use the BaseEvent class.
    """
    global BASE_EVENT_SYSTEM
    BASE_EVENT_SYSTEM = event_system
    BaseEvent.event_system = event_system


def get_event_system() -> EventSystem:
    """Get the global event system for the BaseEvent class."""
    return BASE_EVENT_SYSTEM


def subscribe(priority: int = 0, critical: bool = False) -> EventHandlerDecorator[E]:
    """Subscribe to an event in the global event system."""
    return BASE_EVENT_SYSTEM.subscribe(priority=priority, critical=critical)


def unsubscribe(func: EventHandler[Event]):
    """Unsubscribe from an event in the global event system."""
    BASE_EVENT_SYSTEM.unsubscribe(func)


def unsubscribe_all(cls: type[Event]):
    """Unsubscribe all event handlers from an event in the global event system."""
    BASE_EVENT_SYSTEM.unsubscribe_all(cls)


def emit(event: E) -> None:
    """Emit an event in the global event system."""
    BASE_EVENT_SYSTEM.emit(event)


async def emit_async(event: E) -> None:
    """Emit an event in the global event system asynchronously."""
    await BASE_EVENT_SYSTEM.emit_async(event)
