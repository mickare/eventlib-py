# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Core of the event system framework.
"""

import asyncio
import bisect
import dataclasses
import enum
import inspect
import weakref
from abc import ABC
from contextlib import AsyncExitStack, ExitStack
from typing import (
    Any,
    Callable,
    Generic,
    Iterable,
    Iterator,
    Self,
    TypeGuard,
    TypeVar,
    cast,
)

from eventlib.type_utils import (
    assert_not_async,
    assert_not_async_generator,
    assert_not_generator,
    is_async_context_manager,
    is_context_manager,
)

# Astroid (pylint) does not resolve these documented `inspect` module constants and reports
# them as missing members, so they are bound once here instead of at the usage site.
# pylint: disable=no-member
_CO_VARARGS = inspect.CO_VARARGS
_CO_VARKEYWORDS = inspect.CO_VARKEYWORDS


# pylint: disable=too-few-public-methods
class Event(ABC):
    """Event class that can be extended to create custom events."""


E = TypeVar("E", bound=Event)
"""Generic type variable for events."""

EventHandler = Callable[[E], Any]
"""Generic alias for an event function."""

EventHandlerDecorator = Callable[[EventHandler[E]], EventHandler[E]]
"""Generic alias for an event function decorator."""


class HandlerType(enum.Enum):
    """Type of the event handler function."""

    UNKNOWN = 0
    FUNCTION = 1
    CONTEXT = 2
    ASYNC_FUNCTION = 3
    ASYNC_CONTEXT = 4

    def is_async(self) -> bool:
        """True if the handler is an async function or async context manager."""
        return self in (HandlerType.ASYNC_FUNCTION, HandlerType.ASYNC_CONTEXT)


@dataclasses.dataclass(frozen=True, slots=True)
class EventSubMetadata:
    """Metadata for an event subscription."""

    priority: int = 0
    critical: bool = False
    caching: bool = True


class EventSub(Generic[E]):
    """
    Subscription to an event.

    This object is shared between all event chains that subscribe to the same event.
    It caches the handler type and call method for performance, so that it doesn't have to be determined every time.
    """

    __slots__ = (
        "_event_type",
        "_handler",
        "_meta",
        "_handler_hash",
        "_handler_type",
        "call",
        "call_async",
    )

    def __init__(self, event_type: type[E], handler: EventHandler[E], meta: EventSubMetadata) -> None:
        """
        Create a new event subscription.

        :param event_type: The type of the event.
        :param handler: The handler function.
        :param meta: The subscription metadata.
        """
        self._event_type = event_type
        self._handler = handler
        self._meta = meta
        self._handler_hash = hash((event_type, handler, meta.priority))
        self._handler_type = HandlerType.UNKNOWN
        if inspect.iscoroutinefunction(self._handler):
            self._handler_type = HandlerType.ASYNC_FUNCTION
        # will be replaced by _call() and _call_async()
        self.call: Callable[[E, ExitStack | None], Any] = self._call
        self.call_async: Callable[[E, AsyncExitStack | None], Any] = self._acall

    @property
    def handler(self) -> EventHandler[E]:
        """The handler function."""
        return self._handler

    @property
    def meta(self) -> EventSubMetadata:
        """The metadata of the handler."""
        return self._meta

    @property
    def priority(self) -> int:
        """The priority of the handler."""
        return self._meta.priority

    @property
    def critical(self) -> bool:
        """The criticality of the handler."""
        return self._meta.critical

    @property
    def handler_type(self) -> HandlerType:
        """The type of the handler, or HandlerType.Unknown if not determined yet."""
        return self._handler_type

    @property
    def event_type(self) -> type[E]:
        """The type of the subscribed event."""
        return self._event_type

    def __hash__(self):
        return self._handler_hash

    def __eq__(self, other):
        if isinstance(other, EventSub):
            return self._handler_hash == other._handler_hash
        return False

    @property
    def requires_context(self) -> bool:
        """True if the handler requires a context manager."""
        return self._handler_type in (HandlerType.CONTEXT, HandlerType.ASYNC_CONTEXT)

    def _call(self, event: E, stack: ExitStack | None) -> None:
        """
        Call the handler function synchronously and remember the call method.

        `stack` is only ``None`` once the chain has established that none of its handlers
        need a context manager. On the first emit, and whenever a handler does need one,
        a real `ExitStack` is passed. The value is therefore only dereferenced in the
        branch where the handler actually returned a context manager.
        """
        result = self._handler(event)
        assert_not_async(result, self._handler)
        assert_not_generator(result, self._handler)
        if is_context_manager(result):
            assert stack is not None, "context manager handler requires an exit stack"
            stack.enter_context(result)
            # Remember
            if self._meta.caching:
                self.call = self.__call__context  # type: ignore[assignment]
            self._handler_type = HandlerType.CONTEXT
        # Remember
        else:
            if self._meta.caching:
                self.call = self.__call__sync
            self._handler_type = HandlerType.FUNCTION

    async def _acall(self, event: E, stack: AsyncExitStack | None) -> None:
        """
        Call the handler function asynchronously and remember the call method.

        `stack` is only ``None`` once the chain has established that none of its handlers
        need a context manager. On the first emit, and whenever a handler does need one,
        a real `AsyncExitStack` is passed. The value is therefore only dereferenced in the
        branch where the handler actually returned a context manager.
        """
        result = self._handler(event)
        assert_not_async_generator(result, self._handler)
        assert_not_generator(result, self._handler)
        if is_async_context_manager(result):
            assert stack is not None, "async context manager handler requires an exit stack"
            await stack.enter_async_context(result)
            # Remember
            if self._meta.caching:
                self.call_async = self.__acall__async_context  # type: ignore[assignment]
            self._handler_type = HandlerType.ASYNC_CONTEXT
        elif inspect.isawaitable(result):
            await result
            # Remember
            if self._meta.caching:
                self.call_async = self.__acall__async
            self._handler_type = HandlerType.ASYNC_FUNCTION
        elif is_context_manager(result):
            assert stack is not None, "context manager handler requires an exit stack"
            stack.enter_context(result)
            # Remember
            if self._meta.caching:
                self.call_async = self.__acall__context  # type: ignore[assignment]
                self.call = self.__call__context  # type: ignore[assignment]
            self._handler_type = HandlerType.CONTEXT
        # Remember
        else:
            if self._meta.caching:
                self.call_async = self.__acall__sync
                # The handler is proven plain sync, so a sync emit can use the direct
                # callable as well (this also lets a later async emit take the shortcut).
                self.call = self.__call__sync
            self._handler_type = HandlerType.FUNCTION

    def __call__context(self, event: E, stack: ExitStack):
        stack.enter_context(self._handler(event))

    def __call__sync(self, event: E, _: Any):
        self._handler(event)

    async def __acall__async_context(self, event: E, stack: AsyncExitStack):
        await stack.enter_async_context(self._handler(event))

    async def __acall__async(self, event: E, _: Any):
        await self._handler(event)

    async def __acall__context(self, event: E, stack: AsyncExitStack):
        stack.enter_context(self._handler(event))

    async def __acall__sync(self, event: E, _: Any):
        """Coroutine form of a plain sync handler, kept for callers that await `call_async`."""
        self._handler(event)


class EventChain(Generic[E]):
    """Chain of event subscriptions for a specific event type."""

    __slots__ = ("event_type", "subs", "no_context")

    def __init__(self, event_type: type[E], subs: Iterable[EventSub[E]] = ()) -> None:
        """
        Create a new event chain.

        :param event_type: The type of the event.
        :param subs: The initial subscriptions (optional).
        """
        self.event_type = event_type
        self.subs: list[EventSub[E]] = list(subs)
        self.subs.sort(key=lambda x: x.priority)
        self.no_context: bool | None = None  # None = We don't know (yet)!

    def __len__(self) -> int:
        return len(self.subs)

    def __iter__(self) -> Iterator[EventSub[E]]:
        return iter(self.subs)

    def copy(self) -> Self:
        """Create a copy of the event chain."""
        return EventChain(self.event_type, self.subs)  # type: ignore

    def add(self, sub: EventSub[E]):
        """
        Add a new subscription to the chain, keeping it sorted by priority.

        The insert position is located with a binary search (`bisect.insort`), which costs
        O(log n) comparisons plus the O(n) list shift, instead of the O(n log n) full
        re-sort used previously. Subscribers with equal priority keep their insertion
        order, matching the stable sort behaviour this replaces.
        """
        bisect.insort(self.subs, sub, key=lambda s: s.priority)
        self.no_context = None  # None = We don't know (yet)!

    def remove(self, func: EventHandler):
        """Remove a subscription from the chain."""
        self.subs = [sub for sub in self.subs if sub.handler != func]

    def remove_type(self, event_type: type[E]):
        """Remove all subscriptions for a specific event type from the chain."""
        self.subs = [sub for sub in self.subs if sub.event_type != event_type]

    def _run(self, event: E, stack: ExitStack | None) -> None:
        """
        Invoke every subscription in order, collecting errors.

        Shared by both `call` paths so that the error semantics (collect all failures,
        stop at a `critical` handler, always raise an `ExceptionGroup`) live in one place.
        """
        exceptions = None
        try:
            for sub in self.subs:
                try:
                    sub.call(event, stack)
                # pylint: disable-next=broad-exception-caught
                except Exception as exc:
                    if exceptions is None:
                        exceptions = [exc]
                    else:
                        exceptions.append(exc)
                    if sub.critical:
                        break  # Stop event processing
        finally:
            if exceptions:
                raise ExceptionGroup("Event error", exceptions)

    async def _run_async(self, event: E, stack: AsyncExitStack | None) -> None:
        """
        Invoke every subscription in order, collecting errors.

        Shared by both `call_async` paths. A timeout aborts processing immediately; any
        other error is collected and only aborts early for a `critical` handler.
        """
        exceptions: list[Exception] | None = None
        try:
            for sub in self.subs:
                try:
                    await sub.call_async(event, stack)
                except asyncio.TimeoutError as exc:
                    exceptions = [exc]
                    break  # Stop event processing
                # pylint: disable-next=broad-exception-caught
                except Exception as exc:
                    if exceptions is None:
                        exceptions = [exc]
                    else:
                        exceptions.append(exc)
                    if sub.critical:
                        break  # Stop event processing
        finally:
            if exceptions:
                raise ExceptionGroup("Event error", exceptions)

    def call(self, event: E):
        """Call all event subscriptions synchronously."""
        subs = self.subs
        if not subs:
            return
        if self.no_context:
            # Fast path: no handler needs a context manager, so no ExitStack is created
            # and `None` is passed instead.
            self._run(event, None)
            return
        with ExitStack() as stack:
            self._run(event, stack)
            if self.no_context is None:
                self.no_context = not any(sub.requires_context for sub in subs)

    async def call_async(self, event: E):
        """Call all event subscriptions asynchronously."""
        subs = self.subs
        if not subs:
            return
        if self.no_context:
            # Fast path: neither an AsyncExitStack nor a coroutine per sync handler is
            # needed, which is where most of the async dispatch overhead came from.
            await self._run_async(event, None)
            return
        async with AsyncExitStack() as stack:
            await self._run_async(event, stack)
            if self.no_context is None:
                self.no_context = not any(sub.requires_context for sub in subs)


_EVENT_PARENT_CACHE: weakref.WeakKeyDictionary[type[Event], tuple[type[Event], ...]] = weakref.WeakKeyDictionary()
"""Cache of resolved event parents, keyed by event class. Class hierarchies are static."""


def _get_event_parents(cls: type[Event]) -> tuple[type[Event], ...]:
    """
    Get all parent classes of an event class that are also event classes.

    The result only depends on the class hierarchy, which cannot change after class
    creation, so it is computed once and cached.
    """
    cached = _EVENT_PARENT_CACHE.get(cls)
    if cached is not None:
        return cached

    def _get(clazz: type[Event], _result: dict[type[Event], None]):
        parents = tuple(c for c in clazz.__bases__ if issubclass(c, Event))
        _result.update(((c, None) for c in parents))
        for parent in parents:
            _result.update(_get(parent, _result))
        return _result

    parents = tuple(_get(cls, {}).keys())
    _EVENT_PARENT_CACHE[cls] = parents
    return parents


def _event_type_from_handler(func: EventHandler) -> type[Event]:
    """
    Determine the event type from the handler's first parameter annotation.

    This is a fast path that reads ``__annotations__`` directly instead of building a full
    ``inspect.Signature`` (roughly 10 us -> 0.1 us). Any callable shape it cannot
    introspect falls back to ``inspect.signature()``, so the observable behaviour -
    including which errors are raised - is unchanged.
    """
    target: Any = func
    skip_first = 0
    if isinstance(target, type):
        # For a class the event parameter lives on __init__, after `self`.
        target = getattr(target, "__init__", None)
        skip_first = 1
    elif getattr(target, "__self__", None) is not None:
        # Bound method: `self` is already bound and must not be counted.
        skip_first = 1

    annotations = getattr(target, "__annotations__", None)
    code = getattr(target, "__code__", None)
    # Variadic wrappers (e.g. ``@contextlib.contextmanager``) hide the real signature
    # behind ``*args, **kwargs``; let inspect.signature() follow ``__wrapped__`` instead.
    variadic = code is not None and bool(code.co_flags & (_CO_VARARGS | _CO_VARKEYWORDS))
    if annotations and code is not None and not variadic:
        if code.co_argcount + code.co_kwonlyargcount - skip_first != 1:
            raise TypeError("Handler function must have exactly one argument")
        names = code.co_varnames
        index = code.co_posonlyargcount + skip_first
        if index < len(names):
            event_type = annotations.get(names[index], inspect.Parameter.empty)
            if event_type is not inspect.Parameter.empty:
                return cast(type[Event], event_type)
        raise TypeError("Event type must be specified if not given as annotation")

    # Fallback for callables without an introspectable code object.
    args = list(inspect.signature(func).parameters.values())
    if (not args) or any(arg.default is not inspect.Parameter.empty for arg in args[1:]):
        raise TypeError("Handler function must have exactly one argument")
    event_type = args[0].annotation
    if event_type is inspect.Parameter.empty:
        raise TypeError("Event type must be specified if not given as annotation")
    return cast(type[Event], event_type)


class EventSystem:
    """The event system that manages event subscriptions and calls."""

    __slots__ = ("chains",)

    def __init__(self, other: "EventSystem | None" = None) -> None:
        """
        Create a new event system or copy an existing one.

        :param other: event system to copy (optional)
        """
        chains = {} if other is None else {k: v.copy() for k, v in other.chains.items()}
        self.chains: dict[type[Event], EventChain] = chains

    def _get_parent_subs(self, event_type: type[E]) -> set[EventSub]:
        """Get all subscribers of the parent classes of an event class."""
        return {s for parent in _get_event_parents(event_type) for s in (self.chains.get(parent) or ())}

    @classmethod
    def _check_event_type(cls, event_type: type[E]) -> TypeGuard[E]:
        """Check if the given type is a valid event type."""
        if not issubclass(event_type, Event):
            raise TypeError(f"{event_type} is not a subclass of Event")
        return True

    def _get_chain(self, event_type: type[E]) -> EventChain[E]:
        """Get the event chain for a given event type."""
        # Note: `EventChain` implements `__len__`, so an empty chain is falsy. Using a
        # truthiness test here would treat a cached-but-empty chain as a cache miss and
        # rebuild it on every emit.
        chain = self.chains.get(event_type)
        if chain is not None:
            return chain
        # Unknown type, try to build from parents
        self._check_event_type(event_type)
        self.chains[event_type] = chain = EventChain(event_type, self._get_parent_subs(event_type))
        return chain

    # pylint: disable=too-many-arguments
    def add_subscriber(
        self,
        func: EventHandler[E],
        event_type: type[E] | None = None,
        *,
        priority: int = 0,
        critical: bool = False,
        caching: bool = True,
    ):
        """
        Add a new event subscriber.

        :param func: The handler function.
        :param event_type: The type of the event (optional).
        :param priority: The priority of the handler (default = 0)
        :param critical: If True, stop event processing if an error occurs (default = False)
        :param caching: If True, cache the handler's call method for performance (default = True)
        """
        resolved: type[E]
        if event_type is None:
            resolved = cast(type[E], _event_type_from_handler(func))
        else:
            resolved = event_type
        # Add subscriber to its event chain
        chain = self._get_chain(resolved)
        sub = EventSub(resolved, func, meta=EventSubMetadata(priority=priority, critical=critical, caching=caching))
        chain.add(sub)
        # Add subscriber to all sub-event chains
        for sub_event_type, sub_chain in self.chains.items():
            if issubclass(sub_event_type, resolved) and sub_chain is not chain:
                sub_chain.add(sub)

    def subscribe(
        self, event_type: type[E] | None = None, /, priority: int = 0, critical: bool = False, caching: bool = True
    ) -> EventHandlerDecorator[E]:
        """
        Subscribe to an event with a decorator.

        :param event_type: The type of the event (optional)
        :param priority: The priority of the handler (default = 0)
        :param critical: If True, stop event processing if an error occurs (default = False)
        :param caching: If True, cache the handler's call method for performance (default = True)
        :return: The decorator
        """

        def decorator(func):
            self.add_subscriber(func, event_type, priority=priority, critical=critical, caching=caching)
            return func

        return decorator

    def unsubscribe(self, func: EventHandler[E]):
        """Unsubscribe a function from all event chains."""
        for chain in self.chains.values():
            chain.remove(func)

    def unsubscribe_all(self, event_type: type[E]):
        """Unsubscribe all functions from an event chain."""
        self.chains.pop(event_type, None)
        for chain in self.chains.values():
            chain.remove_type(event_type)

    def clear_all_subscriptions(self):
        """Clear all event subscriptions."""
        self.chains = {}

    def emit(self, event: E) -> None:
        """Call all event subscribers synchronously."""
        self._get_chain(type(event)).call(event)

    async def emit_async(self, event: E) -> None:
        """Call all event subscribers asynchronously."""
        await self._get_chain(type(event)).call_async(event)
