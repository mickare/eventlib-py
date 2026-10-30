# Copyright 2026 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Smoke tests for the shipped examples.

The examples are documentation: if one of them crashes or blocks, the documentation is
wrong. Several of them print to stdout and one reads from stdin, so they are run in a
subprocess with a closed stdin, a timeout and captured output.

The chat example used to call ``input()`` unconditionally, which raised ``EOFError`` when
stdin was not a terminal and blocked forever when it was. These tests exist so that cannot
come back unnoticed.
"""

import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
"""Directory holding the runnable examples."""

EXAMPLES = sorted(path for path in EXAMPLES_DIR.rglob("*.py") if path.name != "__init__.py")
"""Every runnable example module."""

TIMEOUT_SECONDS = 60
"""Generous upper bound; a hang is a failure, not a slow test."""


def test_examples_are_discovered():
    """Guard against the glob silently matching nothing."""
    assert len(EXAMPLES) >= 9
    names = {path.name for path in EXAMPLES}
    assert "chat.py" in names
    assert "worker_queue.py" in names


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda path: path.relative_to(EXAMPLES_DIR).as_posix())
def test_example_runs_non_interactively(example: Path):
    """
    Run an example with stdin closed.

    A non-zero exit fails the test, and so does exceeding the timeout - a blocking
    ``input()`` shows up as a timeout here rather than hanging the test session.
    """
    try:
        completed = subprocess.run(
            [sys.executable, str(example)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
            cwd=EXAMPLES_DIR.parent,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{example.name} did not finish within {TIMEOUT_SECONDS}s (it probably waits on input)")

    assert completed.returncode == 0, (
        f"{example.name} exited with {completed.returncode}\n"
        f"--- stdout ---\n{completed.stdout}\n"
        f"--- stderr ---\n{completed.stderr}"
    )
    assert "Traceback" not in completed.stderr


def test_chat_example_exits_on_eof():
    """The chat example must treat end-of-input as 'stop', not as an error."""
    completed = subprocess.run(
        [sys.executable, str(EXAMPLES_DIR / "use_cases" / "chat.py")],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        check=False,
        cwd=EXAMPLES_DIR.parent,
    )
    assert completed.returncode == 0
    assert "EOFError" not in completed.stderr


def test_chat_example_handles_piped_messages():
    """Piped messages must be processed, and 'exit' must end the loop."""
    completed = subprocess.run(
        [sys.executable, str(EXAMPLES_DIR / "use_cases" / "chat.py")],
        input="hello\nexit\n",
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        check=False,
        cwd=EXAMPLES_DIR.parent,
    )
    assert completed.returncode == 0
    assert "You: hello" in completed.stdout
