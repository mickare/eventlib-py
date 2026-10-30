# Copyright 2026 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Benchmarks of the main user journeys.

These cases reproduce the shapes users actually build with the library, taken from
``examples/``. Unlike the micro-benchmarks they measure realistic *scenarios*: a chat
message that can be cancelled, a plugin system with parent events, an async worker queue,
isolated and copied systems, and events declared with ``attrs`` / Pydantic.

A journey usually has no meaningful hand-written twin for the whole scenario, so the
reference is the plain-Python equivalent of the *dispatch* the journey performs. The
reported ratio therefore still answers "what does the event system cost me here?".
"""

import asyncio
import contextlib
import dataclasses
from datetime import datetime
from typing import Any, Callable

from attrs import define as attrs_define
from eventlib import BaseEvent, Event, EventSystem
from pydantic import BaseModel

from ..case import BenchFunc, Case

# pylint: disable=too-few-public-methods,unused-argument,too-many-instance-attributes


# --------------------------------------------------------------------------------------------
# Journey: chat with cancellation (examples/use_cases/chat.py)
# --------------------------------------------------------------------------------------------
@dataclasses.dataclass()
class ChatEvent(BaseEvent):
    """A chat message that handlers may cancel."""

    name: str
    message: str
    cancelled: bool = False


def _chat_cancel(event: ChatEvent) -> None:
    """Cancel messages that start with 'cancel'."""
    if event.message.startswith("cancel"):
        event.cancelled = True


def _chat_print(event: ChatEvent) -> None:
    """Render the message."""


def _chat_audit(event: ChatEvent) -> None:
    """Record the message for auditing."""


@contextlib.contextmanager
def _chat_guard(_: ChatEvent):
    """Context handler wrapping the whole message processing."""
    try:
        yield
    except ValueError:
        pass


def _chat_journey() -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair for one chat message with a priority-ordered handler set."""
    message = ChatEvent(name="Alice", message="hello world")

    def reference() -> None:
        with _chat_guard(message):
            _chat_cancel(message)
            _chat_audit(message)
            _chat_print(message)

    system = EventSystem()
    system.subscribe(priority=-100)(_chat_guard)
    system.subscribe(priority=0)(_chat_cancel)
    system.subscribe(priority=50)(_chat_audit)
    system.subscribe(priority=100)(_chat_print)
    system.emit(message)  # warm
    emit = system.emit

    def library() -> None:
        emit(message)

    return reference, library


# --------------------------------------------------------------------------------------------
# Journey: plugin system with parent events (examples/use_cases/plugin_system.py)
# --------------------------------------------------------------------------------------------
class Plugin:
    """Minimal plugin interface."""

    name = "plugin"

    def load(self) -> None:
        """Load the plugin."""

    def start(self) -> None:
        """Start the plugin."""


@dataclasses.dataclass
class PluginEvent(BaseEvent):
    """Base event for any plugin lifecycle change."""

    plugin: Plugin


class PluginLoadedEvent(PluginEvent):
    """A plugin was loaded."""


class PluginStartedEvent(PluginEvent):
    """A plugin was started."""


def _on_plugin_event(event: PluginEvent) -> None:
    """Generic plugin lifecycle observer."""


def _on_plugin_loaded(event: PluginLoadedEvent) -> None:
    """Plugin-loaded observer."""


def _on_plugin_started(event: PluginStartedEvent) -> None:
    """Plugin-started observer."""


def _plugin_journey() -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair for a lifecycle event observed by parent and own handlers."""
    plugin = Plugin()
    loaded = PluginLoadedEvent(plugin)
    started = PluginStartedEvent(plugin)

    def reference() -> None:
        # A PluginLoadedEvent reaches the PluginEvent and PluginLoadedEvent handlers.
        _on_plugin_event(loaded)
        _on_plugin_loaded(loaded)
        _on_plugin_event(started)
        _on_plugin_started(started)

    system = EventSystem()
    system.subscribe(PluginEvent)(_on_plugin_event)
    system.subscribe(PluginLoadedEvent)(_on_plugin_loaded)
    system.subscribe(PluginStartedEvent)(_on_plugin_started)
    system.emit(loaded)  # warm both chains
    system.emit(started)
    emit = system.emit

    def library() -> None:
        emit(loaded)
        emit(started)

    return reference, library


# --------------------------------------------------------------------------------------------
# Journey: async worker queue (examples/use_cases/worker_queue.py)
# --------------------------------------------------------------------------------------------
@dataclasses.dataclass
class PrintEvent(BaseEvent):
    """Print a message."""

    message: str


@dataclasses.dataclass
class MoreWorkEvents(BaseEvent):
    """Schedule more events."""

    events: list[BaseEvent]


def _on_print(event: PrintEvent) -> None:
    """Consume a print event."""


def _collect_scheduled(event: MoreWorkEvents, sink: list[BaseEvent]) -> None:
    """Record the events scheduled by a fan-out event."""
    sink.extend(event.events)


WORKER_BATCH = 32
"""Print events per queue drain; the fan-out event makes one more emit."""

WORKER_EMITS = WORKER_BATCH + 1
"""Emits per measured call, used as ``inner_loops`` so results are per event."""

ASYNC_WORKER_BATCH = 16
"""Print events per async queue drain."""


def _worker_journey() -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair for draining a batch of queued events.

    One measured call drains ``WORKER_EMITS`` events from a pre-filled queue, so the
    per-event cost is reported after pyperf normalises by ``inner_loops``.
    """
    batch = WORKER_BATCH
    sink: list[BaseEvent] = []

    def make_events() -> list[BaseEvent]:
        events: list[BaseEvent] = [PrintEvent(message=f"message-{index}") for index in range(batch)]
        events.append(MoreWorkEvents(events=[PrintEvent(message="scheduled")]))
        return events

    queue = make_events()

    def reference() -> None:
        sink.clear()
        for event in queue:
            if isinstance(event, PrintEvent):
                _on_print(event)
            elif isinstance(event, MoreWorkEvents):
                _collect_scheduled(event, sink)

    system = EventSystem()
    system.subscribe(PrintEvent)(_on_print)
    system.subscribe(MoreWorkEvents)(lambda event: _collect_scheduled(event, sink))
    for event in queue:
        system.emit(event)  # warm
    emit = system.emit

    def library() -> None:
        sink.clear()
        for event in queue:
            emit(event)

    return reference, library


def _worker_async_journey() -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair for the async queue drain with an async handler."""
    batch = ASYNC_WORKER_BATCH
    events: list[BaseEvent] = [PrintEvent(message=f"message-{index}") for index in range(batch)]
    scheduled: list[BaseEvent] = [PrintEvent(message="scheduled")]

    async def on_print_async(_: PrintEvent) -> None:
        """Async consumer of a print event."""

    async def on_more_work_async(event: MoreWorkEvents) -> None:
        """Async fan-out consumer."""
        scheduled.extend(event.events)

    async def reference() -> None:
        for event in events:
            if isinstance(event, PrintEvent):
                await on_print_async(event)
            elif isinstance(event, MoreWorkEvents):
                await on_more_work_async(event)

    system = EventSystem()
    system.subscribe(PrintEvent)(on_print_async)
    system.subscribe(MoreWorkEvents)(on_more_work_async)
    asyncio.run(system.emit_async(events[0]))  # warm
    emit = system.emit_async

    async def library() -> None:
        for event in events:
            await emit(event)

    return reference, library


# --------------------------------------------------------------------------------------------
# Journey: isolated and copied systems (examples/isolated_systems.py, copied_systems.py)
# --------------------------------------------------------------------------------------------
@dataclasses.dataclass
class ItemEvent(Event):
    """Item event with a payload."""

    value: str


def _on_item(_: ItemEvent) -> None:
    """Item handler."""


def _isolated_journey() -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair for two independent systems that must not see each other."""
    system_a = EventSystem()
    system_b = EventSystem()
    system_a.subscribe(ItemEvent)(_on_item)
    system_b.subscribe(ItemEvent)(_on_item)
    event_a = ItemEvent("a")
    event_b = ItemEvent("b")
    system_a.emit(event_a)  # warm
    system_b.emit(event_b)
    emit_a = system_a.emit
    emit_b = system_b.emit

    def reference() -> None:
        _on_item(event_a)
        _on_item(event_b)

    def library() -> None:
        emit_a(event_a)
        emit_b(event_b)

    return reference, library


def _copied_journey() -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair where a system is copied and then extended.

    The hand-written equivalent copies the handler list and appends the new subscriber.
    The library additionally has to keep its per-type chains consistent, so this is a
    diagnostic case rather than a like-for-like ratio.
    """
    base_handlers: list[Callable[[ItemEvent], Any]] = [_on_item]
    original = EventSystem()
    original.subscribe(ItemEvent)(_on_item)
    original.emit(ItemEvent("warm"))  # warm the original chain

    def reference() -> None:
        copied = list(base_handlers)
        copied.append(_on_item)
        del copied

    def library() -> None:
        extended = EventSystem(original)
        extended.subscribe(ItemEvent)(_on_item)
        del extended

    return reference, library


# --------------------------------------------------------------------------------------------
# Journey: attrs and pydantic events (examples/support_attrs.py, support_pydantic.py)
# --------------------------------------------------------------------------------------------
@attrs_define
class AttrsItemEvent(Event):
    """Event declared with attrs."""

    type: str
    timestamp: datetime
    name: str
    value: int


class PydanticItemEvent(Event, BaseModel):
    """Event declared with Pydantic."""

    type: str
    timestamp: datetime
    name: str
    value: int


def _on_attrs_item(_: AttrsItemEvent) -> None:
    """attrs event handler."""


def _on_pydantic_item(_: PydanticItemEvent) -> None:
    """Pydantic event handler."""


def _attrs_journey() -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair for a received attrs event."""
    event = AttrsItemEvent(type="created", timestamp=datetime(2024, 8, 16, 20, 0), name="event_1", value=1)

    def reference() -> None:
        _on_attrs_item(event)

    system = EventSystem()
    system.subscribe(AttrsItemEvent)(_on_attrs_item)
    system.emit(event)  # warm
    emit = system.emit

    def library() -> None:
        emit(event)

    return reference, library


def _pydantic_journey() -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair for a validated Pydantic event."""
    event = PydanticItemEvent(type="created", timestamp=datetime(2024, 8, 16, 20, 0), name="event_1", value=1)

    def reference() -> None:
        _on_pydantic_item(event)

    system = EventSystem()
    system.subscribe(PydanticItemEvent)(_on_pydantic_item)
    system.emit(event)  # warm
    emit = system.emit

    def library() -> None:
        emit(event)

    return reference, library


# --------------------------------------------------------------------------------------------
# Journey: multiple inheritance diamond (examples/complex_inheritance.py)
# --------------------------------------------------------------------------------------------
class DiamondBase(Event):
    """Base of the diamond."""


class DiamondLeft(DiamondBase):
    """Left branch of the diamond."""


class DiamondRight(DiamondBase):
    """Right branch of the diamond."""


class DiamondMerged(DiamondLeft, DiamondRight):
    """Merged event that inherits from both branches."""


def _on_base(_: DiamondBase) -> None:
    """Base handler."""


def _on_left(_: DiamondLeft) -> None:
    """Left handler."""


def _on_right(_: DiamondRight) -> None:
    """Right handler."""


def _on_merged(_: DiamondMerged) -> None:
    """Merged handler."""


def _diamond_journey() -> tuple[BenchFunc, BenchFunc]:
    """Reference/emit pair where one event must reach four handlers exactly once each."""
    event = DiamondMerged()

    def reference() -> None:
        _on_base(event)
        _on_left(event)
        _on_right(event)
        _on_merged(event)

    system = EventSystem()
    system.subscribe(DiamondBase)(_on_base)
    system.subscribe(DiamondLeft)(_on_left)
    system.subscribe(DiamondRight)(_on_right)
    system.subscribe(DiamondMerged)(_on_merged)
    system.emit(event)  # warm
    emit = system.emit

    def library() -> None:
        emit(event)

    return reference, library


# --------------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------------
CASES = (
    Case(
        name="chat_cancel",
        group="journey",
        description="Chat message with priority-ordered handlers and cancellation",
        reference=lambda: _chat_journey()[0],
        library=lambda: _chat_journey()[1],
    ),
    Case(
        name="plugin_lifecycle",
        group="journey",
        description="Plugin lifecycle events observed through a parent event class",
        reference=lambda: _plugin_journey()[0],
        library=lambda: _plugin_journey()[1],
    ),
    Case(
        name="worker_queue_sync",
        group="journey",
        description="Drain a batch of queued events with sync handlers",
        reference=lambda: _worker_journey()[0],
        library=lambda: _worker_journey()[1],
        inner_loops=WORKER_EMITS,
    ),
    Case(
        name="worker_queue_async",
        group="journey",
        description="Drain a batch of queued events with async handlers",
        reference=lambda: _worker_async_journey()[0],
        library=lambda: _worker_async_journey()[1],
        is_async=True,
        inner_loops=ASYNC_WORKER_BATCH,
    ),
    Case(
        name="isolated_systems",
        group="journey",
        description="Two isolated systems dispatching the same event type",
        reference=lambda: _isolated_journey()[0],
        library=lambda: _isolated_journey()[1],
    ),
    Case(
        name="copied_system",
        group="journey",
        description="Copy an existing system and add one subscriber to the copy",
        reference=lambda: _copied_journey()[0],
        library=lambda: _copied_journey()[1],
        scored=False,
    ),
    Case(
        name="attrs_event",
        group="journey",
        description="Emit an event declared with attrs",
        reference=lambda: _attrs_journey()[0],
        library=lambda: _attrs_journey()[1],
    ),
    Case(
        name="pydantic_event",
        group="journey",
        description="Emit a validated Pydantic event",
        reference=lambda: _pydantic_journey()[0],
        library=lambda: _pydantic_journey()[1],
    ),
    Case(
        name="diamond_inheritance",
        group="journey",
        description="Diamond-inherited event reaching every handler exactly once",
        reference=lambda: _diamond_journey()[0],
        library=lambda: _diamond_journey()[1],
    ),
)
