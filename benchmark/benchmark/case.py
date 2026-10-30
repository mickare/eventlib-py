# Copyright 2026 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Model of a single benchmark case.

A case always compares two implementations of the *same* work:

- ``reference`` is hand-written Python that does the work without the event system.
- ``library`` does the same work through ``eventlib``.

Measuring both with the same harness makes the result unit-free: the ratio
``library / reference`` is the overhead the framework adds. This is the same idea as the
original benchmark, but now every case is a first-class, individually reported entity
instead of a single hard-coded comparison.
"""

import dataclasses
from typing import Any, Callable

BenchFunc = Callable[[], Any]
"""Zero-argument callable measured by pyperf. Async callables are awaited."""

CaseFactory = Callable[[], BenchFunc]
"""Builds the callable to measure. Called once per process, before measuring."""


@dataclasses.dataclass(frozen=True, slots=True)
class Case:
    """A benchmark case comparing a hand-written reference with the library."""

    # pylint: disable=too-many-instance-attributes
    name: str
    """Unique name inside the group."""

    group: str
    """Group the case belongs to (``macro``, ``micro`` or ``journey``)."""

    description: str
    """One line explaining what is measured."""

    reference: CaseFactory
    """Factory for the hand-written reference implementation."""

    library: CaseFactory
    """Factory for the eventlib implementation."""

    is_async: bool = False
    """Whether the measured callables are coroutines that pyperf must await."""

    scored: bool = True
    """Whether the case contributes to the overall score.

    Cases whose hand-written reference is not a fair equivalent (pure diagnostics) set
    this to ``False``. They are still measured and reported.
    """

    inner_loops: int | None = None
    """Operations performed by one measured call, used to normalise the result.

    pyperf divides the measured time by ``loops * inner_loops``. Use this when one call
    processes a batch (for example a queue drain) so the reported value stays
    *per operation*.
    """

    @property
    def id(self) -> str:
        """Stable identifier, also used as the pyperf benchmark name prefix."""
        return f"{self.group}.{self.name}"

    @property
    def reference_name(self) -> str:
        """pyperf name of the reference benchmark."""
        return f"{self.id}.reference"

    @property
    def library_name(self) -> str:
        """pyperf name of the library benchmark."""
        return f"{self.id}.library"
