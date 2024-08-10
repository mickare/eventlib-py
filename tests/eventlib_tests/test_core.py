# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Test the core of the event system.
"""

import asyncio
import contextlib
from typing import Awaitable, Callable
from unittest import mock

import pytest

from eventlib import Event, EventSystem


# pylint: disable=too-few-public-methods
class A(Event):
    """Test event class"""


# pylint: disable=too-few-public-methods
class B(A):
    """Test event class"""


# pylint: disable=too-few-public-methods
class C(B):
    """Test event class"""


@pytest.mark.asyncio
async def test_event():
    """Test the basic event system"""
    # Arrange
    system = EventSystem()
    _sync = mock.Mock(spec_set=Callable)
    _async = mock.AsyncMock(spec_set=Awaitable)
    _context_sync = mock.Mock()
    _context_sync.return_value.__enter__ = mock.Mock()
    _context_sync.return_value.__exit__ = mock.Mock(return_value=False)
    _context_async = mock.Mock()
    _context_async.return_value.__aenter__ = mock.AsyncMock()
    _context_async.return_value.__aexit__ = mock.AsyncMock(return_value=False)
    system.subscribe(B)(_sync)
    system.subscribe(B)(_async)
    system.subscribe(B)(_context_sync)
    system.subscribe(B)(_context_async)
    # Act 0
    event = C()
    await system.emit_async(event)
    # Assert 0
    _sync.assert_called_once_with(event)
    _async.assert_awaited_once_with(event)
    _context_sync.assert_called_once_with(event)
    _context_async.assert_called_once_with(event)
    _context_sync.return_value.__enter__.assert_called_once()
    _context_async.return_value.__aenter__.assert_awaited_once()
    # Act 1
    other = A()
    await system.emit_async(other)
    # Assert 1
    assert _sync.call_count == 1
    assert _async.await_count == 1
    assert _context_sync.call_count == 1
    assert _context_async.call_count == 1
    assert _context_sync.return_value.__enter__.call_count == 1
    assert _context_async.return_value.__aenter__.await_count == 1
    # Act 2
    event = B()
    await system.emit_async(event)
    # Assert 2
    assert _sync.call_count == 2
    assert _async.await_count == 2
    assert _context_sync.call_count == 2
    assert _context_async.call_count == 2
    assert _context_sync.return_value.__enter__.call_count == 2
    assert _context_async.return_value.__aenter__.await_count == 2
    # Act x
    event = C()
    for _ in range(8):
        await system.emit_async(event)
    # Assert 2
    assert _sync.call_count == 10
    assert _async.await_count == 10
    assert _context_sync.call_count == 10
    assert _context_async.call_count == 10
    assert _context_sync.return_value.__enter__.call_count == 10
    assert _context_async.return_value.__aenter__.await_count == 10


@pytest.mark.asyncio
async def test_priority(system):
    """Test the priority of event handlers"""
    # Arrange
    results = []
    system.subscribe(A, priority=-1)(lambda _: results.append(-1))
    system.subscribe(A)(lambda _: results.append(0))
    system.subscribe(A, priority=1)(lambda _: results.append(1))
    # Act
    await system.emit_async(A())
    # Assert
    assert results == [-1, 0, 1]


@pytest.mark.asyncio
async def test_context(system):
    """Test that context manager work."""
    # Arrange
    results = []

    @system.subscribe(A, priority=-1)
    @contextlib.asynccontextmanager
    async def first(_):
        results.append(-1)
        yield
        results.append(-1)

    @system.subscribe(A, priority=0)
    @contextlib.contextmanager
    def second(_):
        results.append(0)
        yield
        results.append(0)

    system.subscribe(A, priority=1)(lambda _: results.append(1))
    system.subscribe(A, priority=1337)(lambda _: results.append(1337))
    # Act
    await system.emit_async(A())
    # Assert
    assert results == [-1, 0, 1, 1337, 0, -1]


# pylint: disable=unused-argument
def test_usage_annotation(system):
    """Test usage of subscribing with annotation"""

    def handle(event: A):
        """A function that can subscribe to events."""

    class Handler:
        """An event handler that uses the constructor to subscribe and is a context manager."""

        def __init__(self, event: A):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    # pylint: disable=too-few-public-methods
    class Other:
        """Some class method that can subscribe to events."""

        def handle(self, event: A):
            """Method to handle events"""

    system.subscribe()(handle)
    system.subscribe()(Handler)
    system.subscribe()(Other().handle)
    system.emit(A())


def test_usage_annotation_missing(system):
    """Test usage error on missing annotation."""

    def handle(_):
        pass

    with pytest.raises(TypeError):
        system.subscribe()(handle)


# pylint: disable=unused-argument
def test_usage_annotation_too_many_args(system):
    """Test usage error on too many arguments."""

    def handle(event, other):  # noqa
        pass

    with pytest.raises(TypeError):
        system.subscribe()(handle)  # type:ignore


@pytest.mark.asyncio
async def test_handler_usage_no_async_func(system):
    """Test error on non-async function"""

    _awaitable = asyncio.get_running_loop().create_future()

    def _call(_: A):
        return _awaitable

    system.subscribe(A)(_call)
    # with warnings.catch_warnings(action="error", category=RuntimeWarning):
    with pytest.raises(ExceptionGroup) as exc:
        system.emit(A())
    assert len(exc.value.exceptions) == 1
    assert isinstance(exc.value.exceptions[0], TypeError)


def test_handler_usage_no_async_context(system):
    """Test handler error on non-async context manager"""

    @contextlib.asynccontextmanager
    async def _context(_: A):
        yield

    system.subscribe(A)(_context)
    with pytest.raises(ExceptionGroup) as exc:
        system.emit(A())
    assert len(exc.value.exceptions) == 1
    assert isinstance(exc.value.exceptions[0], TypeError)


def test_handler_error(system):
    """Test handler error"""
    system.subscribe(A)(lambda _: 1 / 0)
    with pytest.raises(ExceptionGroup) as exc:
        system.emit(A())
    assert len(exc.value.exceptions) == 1
    assert isinstance(exc.value.exceptions[0], ZeroDivisionError)


@pytest.mark.asyncio
async def test_handler_error_async(system):
    """Async test handler error"""
    system.subscribe(A)(lambda _: 1 / 0)
    with pytest.raises(ExceptionGroup) as exc:
        await system.emit_async(A())
    assert len(exc.value.exceptions) == 1
    assert isinstance(exc.value.exceptions[0], ZeroDivisionError)


@pytest.mark.asyncio
async def test_emit_timeout_with_error_async(system):
    """Async test for emitting events with timeout and handler error combined"""
    system.subscribe(A)(lambda _: 1 / 0)
    system.subscribe(A)(lambda _: asyncio.sleep(1))
    with pytest.raises(ExceptionGroup) as exc:
        await asyncio.wait_for(system.emit_async(A()), timeout=0.01)
    assert len(exc.value.exceptions) == 1
    assert isinstance(exc.value.exceptions[0], ZeroDivisionError)


def test_emit(system):
    """Test for emitting events"""
    # Arrange
    _call = mock.Mock(Callable, name="_call")
    _context = mock.Mock(Callable, name="_context")
    _context.return_value.__enter__ = mock.Mock(Callable)
    _context.return_value.__exit__ = mock.Mock(Callable)
    system.add_subscriber(_call, A)
    system.add_subscriber(_context, A)
    # Act
    event1 = A()
    system.emit(event1)
    # Assert
    _call.assert_called_once_with(event1)
    _context.assert_called_once_with(event1)
    _context.return_value.__enter__.assert_called()
    _context.return_value.__exit__.assert_called()
    # Act
    event2 = A()
    system.emit(event2)
    # Assert
    _call.assert_has_calls([mock.call(event1), mock.call(event2)])
    _context.assert_has_calls([mock.call(event1), mock.call(event2)], any_order=True)
    assert _context.return_value.__enter__.call_count == 2
    assert _context.return_value.__exit__.call_count == 2


@pytest.mark.asyncio
async def test_emit_async(system):
    """Async test for emitting events"""

    # Arrange
    _call = mock.AsyncMock(Callable, name="_call")
    _context = mock.Mock(Callable, name="_context")
    _context.return_value.__aenter__ = mock.AsyncMock(Callable)
    _context.return_value.__aexit__ = mock.AsyncMock(Callable)
    system.add_subscriber(_call, A)
    system.add_subscriber(_context, A)
    # Act
    event1 = A()
    await system.emit_async(event1)
    # Assert
    _call.assert_awaited_once_with(event1)
    _context.assert_called_once_with(event1)
    _context.return_value.__aenter__.assert_awaited_once()
    _context.return_value.__aexit__.assert_awaited_once()
    # Act
    event2 = A()
    await system.emit_async(event2)
    # Assert
    _call.assert_has_awaits([mock.call(event1), mock.call(event2)])
    _context.assert_has_calls([mock.call(event1), mock.call(event2)], any_order=True)
    assert _context.return_value.__aenter__.await_count == 2
    assert _context.return_value.__aexit__.await_count == 2


def test_emit_invalid_event(system):
    """Test error on invalid event type"""
    with pytest.raises(TypeError):
        system.emit(object())  # type: ignore


@pytest.mark.asyncio
async def test_emit_timeout(system):
    """Timeout of event handler"""
    system.subscribe(A)(lambda _: asyncio.sleep(1))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(system.emit_async(A()), timeout=0.01)


@pytest.mark.asyncio
async def test_handler_timeout_async(system):
    """Async timeout of event handler"""

    # Arrange
    @system.subscribe()
    async def _raising(_event: A):
        raise asyncio.TimeoutError()

    _call = mock.Mock(Callable)
    system.subscribe(A, priority=1)(_call)

    # Act & Assert
    event = A()
    with pytest.raises(ExceptionGroup) as exc:
        await system.emit_async(event)
    assert exc.group_contains(asyncio.TimeoutError)
    _call.assert_not_called()


def test_handler_critical(system):
    """Test for critical events"""

    # Arrange
    @system.subscribe(critical=True)
    def _raising(_event: A):
        raise ValueError("test")

    _call = mock.Mock(Callable)
    system.subscribe(A, priority=1)(_call)

    # Act & Assert
    event = A()
    with pytest.raises(ExceptionGroup) as exc:
        system.emit(event)
    assert exc.group_contains(ValueError, match="test")
    _call.assert_not_called()


@pytest.mark.asyncio
async def test_handler_critical_async(system):
    """Async test for critical events"""

    # Arrange
    @system.subscribe(critical=True)
    async def _raising(_event: A):
        raise ValueError("test")

    _call = mock.Mock(Callable)
    system.subscribe(A, priority=1)(_call)

    # Act & Assert
    event = A()
    with pytest.raises(ExceptionGroup) as exc:
        await system.emit_async(event)
    assert exc.group_contains(ValueError, match="test")
    _call.assert_not_called()


def test_handler_no_context(system):
    """Test error of handler that returns a generator"""

    # Arrange
    @system.subscribe(critical=True)
    def invalid_generator(event: A):
        yield

    # Act & Assert
    event = A()
    with pytest.raises(ExceptionGroup) as exc:
        system.emit(event)
    exc.group_contains(TypeError, match="Cannot handle generator.")


@pytest.mark.asyncio
async def test_handler_no_context_async(system):
    """Test error of handler that returns a generator"""

    # Arrange
    @system.subscribe(critical=True)
    async def invalid_generator(event: A):
        yield

    # Act & Assert
    event = A()
    with pytest.raises(ExceptionGroup) as exc:
        await system.emit_async(event)
    exc.group_contains(TypeError, match="Cannot handle async generator.")
