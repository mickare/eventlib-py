# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Example of copying and extending event systems.
"""

import dataclasses

from eventlib import Event, EventSystem


@dataclasses.dataclass
class Foo(Event):
    """Simple event with a value."""

    value: str


@dataclasses.dataclass
class Bar(Event):
    """Simple event with a value."""

    value: str


original = EventSystem()


@original.subscribe()
def on_foo(event: Foo):
    """Event handler for Foo events - in both event systems."""
    print(f"on_foo({event})")


# Copy of the outer event system
extended = EventSystem(original)


@extended.subscribe()
def on_bar(event: Bar):
    """Event handler for Bar events - only in the extended event system."""
    print(f"on_bar({event})")


# ==================================================================================================
# Example
def copy_example():
    """
    Example of a copied event system.

    Output::

        on_foo(Foo(value='Foo'))
        ---
        on_foo(Foo(value='Hello'))
        on_bar(Bar(value='World'))

    """
    original.emit(Foo(value="Foo"))
    original.emit(Bar(value="Bar"))  # Nothing happens
    print("---")
    extended.emit(Foo(value="Hello"))
    extended.emit(Bar(value="World"))


if __name__ == "__main__":
    copy_example()
