# Copyright 2026 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Benchmark cases.

``macro``
    End-to-end cost of one realistic emit against a hand-written reference.
``micro``
    One dispatch dimension at a time, so handler cost cannot mask framework cost.
``journey``
    The scenarios users actually build, taken from ``examples/``.
"""

from .registry import ALL_CASES, BY_ID, BY_NAME, GROUPS, select_cases

__all__ = ["ALL_CASES", "BY_ID", "BY_NAME", "GROUPS", "select_cases"]
