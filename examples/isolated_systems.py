# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Example of isolated event systems.
"""

import dataclasses

from eventlib import Event, EventSystem

system_a = EventSystem()
system_b = EventSystem()


@dataclasses.dataclass
class MyEvent(Event):
    """Simple event with a value."""

    value: str
    system: str | None = None


@system_a.subscribe()
def on_event_a(event: MyEvent):
    """Event handler for MyEvent events in system A."""
    print(f"on_event_a({event})")


@system_b.subscribe()
def on_event_b(event: MyEvent):
    """Event handler for MyEvent events in system B."""
    print(f"on_event_b({event})")


# ==================================================================================================
# Example
def isolated_example():
    """
    Example of isolated events.

    Output::

        on_event_a(MyEvent(value='Hello', system='A'))
        on_event_b(MyEvent(value='World', system='B'))

    """
    system_a.emit(MyEvent("Hello", system="A"))
    system_b.emit(MyEvent("World", system="B"))


if __name__ == "__main__":
    isolated_example()
