# Copyright 2026 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""Exceptions raised by the benchmark suite's own logic."""


class BenchmarkError(Exception):
    """A user-facing error: bad selection, unreadable summary, nothing to render.

    The CLI turns this into a non-zero exit code. Library code raises it instead of
    ``SystemExit`` so callers (tests, notebooks, other tools) can handle it normally.
    """
