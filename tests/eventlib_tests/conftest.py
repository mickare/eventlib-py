# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Pytest configuration for the eventlib_tests tests.
"""

import pytest

from eventlib import EventSystem


@pytest.fixture()
def system() -> EventSystem:
    """Event system for testing."""
    return EventSystem()
