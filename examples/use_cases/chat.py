# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Example of a simple chat system with event handlers.
It demonstrates how to use event handlers to cancel messages, print messages, and handle errors.
"""
import contextlib
import dataclasses
import sys

from eventlib import BaseEvent, subscribe


@dataclasses.dataclass()
class ChatEvent(BaseEvent):
    """A simple chat event."""

    name: str
    message: str
    cancelled: bool = False


@subscribe(priority=100)
def on_chat_print(event: ChatEvent):
    """Print the message of the chat event."""
    if not event.cancelled:
        print(f"{event.name}: {event.message}")
    else:
        print(f"{event.name}: cancelled the message.")


@subscribe()
def cancel_message(event: ChatEvent):
    """Cancel the message if it starts with 'cancel'."""
    if event.message.startswith("cancel"):
        event.cancelled = True


@subscribe()
def on_exit_message(event: ChatEvent):
    """Stop the chat if the message starts with 'exit'."""
    if event.message.startswith("exit"):
        sys.exit(0)


@subscribe(critical=True)
def raise_error_with_critical(event: ChatEvent):
    """Raise an error if the message starts with 'fail'."""
    if event.message.startswith("fail"):
        raise ValueError(f"Message {event.message!r} starts with word 'fail'.")


@subscribe(priority=-100)
@contextlib.contextmanager
def on_chat_error(event: ChatEvent):
    """Handle errors in chat events."""
    try:
        yield
    except* ValueError as exc:
        print(f"{event.name}: {exc!r}")


# ==================================================================================================
# Example
def chat_example():
    """
    Example of a simple chat system.

    Press Ctrl+C or enter "exit" to exit the chat.
    """
    print("Enter 'exit' to exit the chat.")
    ChatEvent(name="Alice", message="Hello World").emit()
    ChatEvent(name="Bob", message="fail this message").emit()
    ChatEvent(name="Alice", message="cancel this message").emit()
    while message := input("Enter a message: "):
        ChatEvent(name="You", message=message).emit()


if __name__ == "__main__":
    chat_example()
