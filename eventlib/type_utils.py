# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Module for asserting helpers
"""
import inspect
from typing import Any, AsyncContextManager, ContextManager, TypeGuard


def is_context_manager(obj) -> TypeGuard[ContextManager]:
    """Check if an object is a context manager."""
    return hasattr(obj, "__enter__") and hasattr(obj, "__exit__")


def is_async_context_manager(obj) -> TypeGuard[AsyncContextManager]:
    """Check if an object is an async context manager."""
    return hasattr(obj, "__aenter__") and hasattr(obj, "__aexit__")


if __debug__:

    def assert_not_generator(obj: Any, func: Any = None) -> None:
        """Assert that the object is not a generator."""
        if inspect.isgenerator(obj):
            err = TypeError("Cannot handle generator.")
            if func:
                err.add_note(f"The event function {func!r} returned a generator.")
            err.add_note("Did you forget to annotate a context manager?")
            raise err

    def assert_not_async_generator(obj: Any, func: Any = None) -> None:
        """Assert that the object is not an async generator."""
        if inspect.isasyncgen(obj):
            err = TypeError("Cannot await async generator.")
            if func:
                err.add_note(f"The event function {func!r} returned an async generator.")
            err.add_note("Did you forget to annotate an async context manager?")
            raise err

    def assert_not_async(obj: Any, func: Any = None) -> None:
        """Assert that the object is not any awaitable or async context or async generator."""
        if inspect.isawaitable(obj) or is_async_context_manager(obj) or inspect.isasyncgen(obj):
            err = TypeError("Cannot await in a synchronous event call.")
            if func:
                err.add_note(f"The event function {func!r} returned an async object.")
            raise err

else:

    def assert_not_generator(obj: Any, func: Any) -> None:  # type: ignore
        # pylint: disable=unused-argument,missing-function-docstring
        pass

    def assert_not_async_generator(obj: Any, func: Any) -> None:  # type: ignore
        # pylint: disable=unused-argument,missing-function-docstring
        pass

    def assert_not_async(obj: Any, func: Any) -> None:  # type: ignore
        # pylint: disable=unused-argument,missing-function-docstring
        pass
