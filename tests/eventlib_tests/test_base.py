# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Test for the base events and global event system.
"""

from typing import Callable
from unittest import mock

import pytest

from eventlib import (
    BaseEvent,
    EventSystem,
    emit,
    emit_async,
    get_event_system,
    set_event_system,
    subscribe,
    unsubscribe,
    unsubscribe_all,
)

test_system = EventSystem()


@pytest.fixture(scope="module", autouse=True)
def set_base_system():
    """Fixture to temporary set the global event system to the `test_system`."""
    default = get_event_system()
    try:
        yield set_event_system(test_system)
    finally:
        set_event_system(default)


class BaseA(BaseEvent, event_system=test_system):
    """BaseA event class."""


class BaseB(BaseA):
    """BaseB event class."""


class BaseC(BaseB):
    """BaseC event class."""


def test_base_events():
    """Test the events are correctly set."""
    # Assert
    assert BaseA.event_system is test_system
    assert BaseB.event_system is test_system
    assert BaseC.event_system is test_system


def test_subscribe():
    """Test subscribing to events"""
    test_system.clear_all_subscriptions()

    # Arrange
    _mock_a = mock.Mock(Callable)
    _mock_b = mock.Mock(Callable)
    _mock_c = mock.Mock(Callable)
    BaseA.subscribe()(_mock_a)
    BaseB.subscribe()(_mock_b)
    BaseC.subscribe()(_mock_c)
    # Act
    event1 = BaseB().emit()
    # Assert
    _mock_a.assert_called_once_with(event1)
    _mock_b.assert_called_once_with(event1)
    _mock_c.assert_not_called()


def test_unsubscribe():
    """Test unsubscribing from events."""
    test_system.clear_all_subscriptions()
    _call = mock.Mock(Callable)

    @subscribe()
    def _sub_a(_: BaseA):
        pytest.fail("This should not be called")  # pragma: no cover

    @subscribe()
    def _sub_b(_: BaseB):
        pytest.fail("This should not be called")  # pragma: no cover

    @subscribe()
    def _sub_c(event: BaseC):
        _call(event)

    # Arrange
    unsubscribe(_sub_a)
    unsubscribe_all(BaseB)
    # Act
    BaseB().emit()
    # Assert
    _call.assert_not_called()

    # Act
    event_c = BaseC().emit()
    # Assert
    _call.assert_called_once_with(event_c)


def test_emit():
    """Test emitting events via the global event system."""
    # Arrange
    test_system.clear_all_subscriptions()
    _call = mock.Mock(Callable)
    BaseC.subscribe()(_call)
    event = BaseC()
    # Act
    emit(event)
    # Assert
    _call.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_emit_async():
    """Test emitting events asynchronously via the global event system."""
    # Arrange
    test_system.clear_all_subscriptions()
    _call = mock.AsyncMock(Callable)
    BaseC.subscribe()(_call)
    event = BaseC()
    # Act
    await emit_async(event)
    # Assert
    _call.assert_awaited_once_with(event)
