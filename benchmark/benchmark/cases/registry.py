# Copyright 2026 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Registry of all benchmark cases.

Cases are grouped by what they answer:

``macro``
    End-to-end cost of one realistic emit against a hand-written reference.
``micro``
    One dispatch dimension at a time, so handler cost cannot mask framework cost.
``journey``
    The scenarios users actually build, taken from ``examples/``.
"""

from ..case import Case
from ..errors import BenchmarkError
from . import journey, macro, micro

GROUPS: dict[str, tuple[Case, ...]] = {
    "macro": macro.CASES,
    "micro": micro.CASES,
    "journey": journey.CASES,
}
"""Cases per group, in a stable order (pyperf worker tasks depend on it)."""

ALL_CASES: tuple[Case, ...] = tuple(case for cases in GROUPS.values() for case in cases)
"""Every case, in a stable order."""

BY_ID: dict[str, Case] = {case.id: case for case in ALL_CASES}
"""Cases indexed by their full ``group.name`` identifier."""

BY_NAME: dict[str, tuple[Case, ...]] = {}
"""Cases indexed by their bare name (a name may exist in more than one group)."""
for _registered_case in ALL_CASES:
    BY_NAME[_registered_case.name] = BY_NAME.get(_registered_case.name, ()) + (_registered_case,)


def select_cases(selection: list[str] | None) -> tuple[Case, ...]:
    """
    Resolve a CLI selection into cases, preserving the canonical order.

    A token may be ``all``, a group name, a full case id (``micro.emit_sync_10``) or a
    bare case name (``emit_sync_10``). Bare names must be unambiguous.
    """
    if not selection:
        return ALL_CASES

    wanted: set[str] = set()
    for token in selection:
        if token == "all":
            wanted.update(case.id for case in ALL_CASES)
        elif token in GROUPS:
            wanted.update(case.id for case in GROUPS[token])
        elif token in BY_ID:
            wanted.add(token)
        elif token in BY_NAME:
            matches = BY_NAME[token]
            if len(matches) > 1:
                options = ", ".join(case.id for case in matches)
                raise BenchmarkError(f"case name {token!r} is ambiguous; use one of: {options}")
            wanted.add(matches[0].id)
        else:
            available = ", ".join(case.id for case in ALL_CASES)
            raise BenchmarkError(f"unknown case {token!r}; choose from: {available}")

    return tuple(case for case in ALL_CASES if case.id in wanted)


__all__ = ["ALL_CASES", "BY_ID", "BY_NAME", "GROUPS", "select_cases"]
