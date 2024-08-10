# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Event library for Python with asyncio support.
"""

from .base import (
    BaseEvent,
    emit,
    emit_async,
    get_event_system,
    set_event_system,
    subscribe,
    unsubscribe,
    unsubscribe_all,
)
from .core import Event, EventHandler, EventHandlerDecorator, EventSystem

__all__ = [
    "Event",
    "EventSystem",
    "EventHandlerDecorator",
    "EventHandler",
    "BaseEvent",
    "get_event_system",
    "set_event_system",
    "subscribe",
    "unsubscribe",
    "unsubscribe_all",
    "emit",
    "emit_async",
]
