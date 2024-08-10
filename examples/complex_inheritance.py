# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Example that demonstrates how event handlers work with multiple inheritance.
An event handler is only called once per event, even if it is inherited multiple times.

The class diagram::

         Base
        /    \\
    Left     Right
        \\    /
        Merged


"""

from eventlib import BaseEvent, subscribe


# ==================================================================================================
# Events
class Base(BaseEvent):
    """Base Events for this example"""


class Left(Base):
    """Left class"""


class Right(Base):
    """Right class"""


class Merged(Left, Right):
    """Merged class of both left and right"""


# ==================================================================================================
# Event handlers
@subscribe()
def on_base(event: Base):
    """Handle any base event"""
    print(f"on_base({event!r})")


@subscribe()
def on_left(event: Left):
    """Handle any left event"""
    print(f"on_left({event!r})")


@subscribe()
def on_right(event: Right):
    """Handle any right event"""
    print(f"on_right({event!r})")


@subscribe()
def on_merged(event: Merged):
    """Handle any merged event"""
    print(f"on_merged({event!r})")


# ==================================================================================================
# Example
def inheritance_example():
    """
    Example that demonstrates how event handlers work with multiple inheritance.
    An event handler is only called once per event, even if it is inherited multiple times.
    """
    print("Merged event:")
    Merged().emit()  # prints: on_base(...), on_right(...), on_left(...), on_merged(...)

    print("\nLeft event:")
    Left().emit()  # prints: on_base(...), on_left(...)

    print("\nRight event:")
    Right().emit()  # prints: on_base(...), on_right(...)


if __name__ == "__main__":
    inheritance_example()
