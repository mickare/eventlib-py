# Copyright 2026 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Command line interface of the benchmark suite.

Commands
--------
``list``
    Show the available cases.
``run`` (default)
    Measure the selected cases with pyperf, print a Markdown report and write a summary.
``render``
    Draw the comparison and overhead graphs from a summary.

Any option the suite does not recognise is forwarded to ``pyperf``, so the standard flags
work unchanged: ``-p/--processes``, ``-n/--values``, ``-w/--warmups``, ``--fast``,
``--rigorous``, ``--affinity``, ``--quiet``, … See ``pyperf --help``.

Examples
--------
::

    python -m benchmark list
    python -m benchmark run --select micro --summary results/latest.json
    python -m benchmark run --fast --quiet
    python -m benchmark render --summary results/latest.json --output results/latest.png
"""

import argparse
import os
import sys
from pathlib import Path

import pyperf  # type: ignore[import-untyped]

from .cases import ALL_CASES, select_cases
from .errors import BenchmarkError
from .suite import format_markdown, load_suite, run_cases, save_suite

DEFAULT_SUMMARY = Path("results") / "summary.json"
"""Where ``run`` writes its summary unless told otherwise."""

SELECTION_ENV = "EVENTLIB_BENCH_SELECT"
"""Environment variable carrying the case selection into worker processes."""

DEFAULT_PROCESSES = 40
"""Worker processes per benchmark unless the user passes ``-p/--processes``.

pyperf's own default is 20. Nanosecond-scale dispatch benchmarks have enough
process-to-process jitter that 20 runs routinely trip pyperf's "not enough samples"
warning, so the suite doubles it. ``--fast`` and ``--rigorous`` still take precedence.
"""

COMMANDS = ("list", "run", "render")
"""Recognised subcommands."""


# --------------------------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the suite's own options."""
    parser = argparse.ArgumentParser(
        prog="benchmark",
        description="pyperf benchmark suite for eventlib-py.",
        epilog="Unrecognised options are forwarded to pyperf (see `pyperf --help`).",
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list", help="list the available benchmark cases", allow_abbrev=False)

    run = subparsers.add_parser("run", help="measure the selected cases (default)", allow_abbrev=False)
    run.add_argument(
        "-s",
        "--select",
        action="append",
        metavar="CASE",
        help="case, group or 'all' to run; repeatable (default: all)",
    )
    run.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY,
        metavar="FILE",
        help=(f"write the summary to FILE (default: {DEFAULT_SUMMARY}; " "skipped when pyperf's -o/--output is used)"),
    )
    run.add_argument("--no-summary", action="store_true", help="do not write a summary file")
    run.add_argument("--no-report", action="store_true", help="do not print the Markdown report")

    render = subparsers.add_parser("render", help="render graphs from a summary", allow_abbrev=False)
    render.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY,
        metavar="FILE",
        help=f"summary to render (default: {DEFAULT_SUMMARY})",
    )
    render.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        metavar="FILE",
        help="write the figure to FILE instead of opening a window",
    )

    return parser


def _program_args() -> list[str]:
    """Interpreter arguments pyperf must use to re-spawn this program as a worker."""
    program_args = ["-m", "benchmark"]
    if sys.flags.optimize:
        program_args.insert(0, "-" + "O" * sys.flags.optimize)
    return program_args


def _writes_pyperf_output(pyperf_args: list[str]) -> bool:
    """Whether pyperf was asked to write its own result file (``-o/--output``).

    In that case the suite's summary is redundant, and writing it to its default path
    would surprise the user with a second file they did not ask for.
    """
    return any(arg in ("-o", "--output") or arg.startswith("--output=") for arg in pyperf_args)


def _with_default_processes(pyperf_args: list[str]) -> list[str]:
    """
    Apply `DEFAULT_PROCESSES` unless the user chose a process count.

    ``--fast`` and ``--rigorous`` are presets that override the process count inside
    pyperf, so they are left untouched.
    """
    if any(arg in ("--fast", "--rigorous") for arg in pyperf_args):
        return pyperf_args
    for arg in pyperf_args:
        if arg in ("-p", "--processes") or arg.startswith(("--processes=", "-p")):
            return pyperf_args
    return [*pyperf_args, "--processes", str(DEFAULT_PROCESSES)]


def _with_inherited_selection(pyperf_args: list[str], selection: list[str] | None) -> list[str]:
    """
    Ensure the case selection reaches the worker processes.

    pyperf builds the worker command line itself, so the selection cannot be forwarded as
    an argument. It is passed through the environment instead, which pyperf only copies
    when the variable is listed in ``--inherit-environ`` (or ``--copy-env`` is used).
    """
    if not selection or any(arg.startswith("--copy-env") for arg in pyperf_args):
        return pyperf_args

    for index, arg in enumerate(pyperf_args):
        if arg == "--inherit-environ" and index + 1 < len(pyperf_args):
            names = pyperf_args[index + 1].split(",")
            if SELECTION_ENV not in names:
                pyperf_args[index + 1] = ",".join((*names, SELECTION_ENV))
            return pyperf_args
        if arg.startswith("--inherit-environ="):
            names = arg.split("=", 1)[1].split(",")
            if SELECTION_ENV not in names:
                pyperf_args[index] = f"--inherit-environ={','.join((*names, SELECTION_ENV))}"
            return pyperf_args

    return [*pyperf_args, f"--inherit-environ={SELECTION_ENV}"]


# --------------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------------
def _cmd_list() -> int:
    """Print the available cases."""
    current_group = None
    for case in ALL_CASES:
        if case.group != current_group:
            current_group = case.group
            print(f"\n{current_group}:")
        marker = "" if case.scored else "  (diagnostic, not scored)"
        print(f"  {case.id:<34} {case.description}{marker}")
    print()
    return 0


def _cmd_run(args: argparse.Namespace, pyperf_args: list[str]) -> int:
    """Measure the selected cases."""
    cases = select_cases(args.select)
    if not cases:
        print("No cases selected.", file=sys.stderr)
        return 2

    if args.select:
        os.environ[SELECTION_ENV] = ",".join(args.select)
    pyperf_args = _with_default_processes(pyperf_args)
    pyperf_args = _with_inherited_selection(pyperf_args, args.select)

    runner = pyperf.Runner(program_args=tuple(_program_args()))
    runner.parse_args(pyperf_args)

    result = run_cases(cases, runner)

    if not args.no_report:
        print()
        print(format_markdown(result))

    if not args.no_summary and not _writes_pyperf_output(pyperf_args):
        save_suite(result, args.summary)
        print(f"Summary written to {args.summary}")

    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    """Render graphs from a summary."""
    from .render import render_suite  # pylint: disable=import-outside-toplevel

    render_suite(load_suite(args.summary), args.output)
    return 0


# --------------------------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """Run the CLI in the parent process."""
    argv = list(sys.argv[1:] if argv is None else argv)

    # pyperf re-spawns this program for every benchmark. A worker is identified by
    # `--worker` and must not go through the suite's own argument parsing.
    if "--worker" in argv:
        return worker_main(argv)

    parser = _build_parser()

    # Bare `benchmark`, `benchmark --help` and `benchmark -h` show the top-level help
    # rather than silently defaulting to `run`, which would hide the subcommands.
    if not argv or argv == ["-h"] or argv == ["--help"]:
        parser.print_help()
        print("\npyperf options (forwarded by `run`):")
        pyperf.Runner(add_cmdline_args=None).argparser.print_help()
        return 0

    if argv[0] in COMMANDS:
        args, pyperf_args = parser.parse_known_args(argv)
    else:
        # Default command: everything belongs to `run`.
        args, pyperf_args = parser.parse_known_args(["run", *argv])

    try:
        return _dispatch(args, pyperf_args)
    except BenchmarkError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace, pyperf_args: list[str]) -> int:
    """Run the selected subcommand."""
    if args.command == "list":
        return _cmd_list()
    if args.command == "render":
        return _cmd_render(args)
    return _cmd_run(args, pyperf_args)


def worker_main(argv: list[str]) -> int:
    """
    Run the suite inside a pyperf worker process.

    The worker only has to reproduce the parent's ``Runner`` construction and benchmark
    order; the case selection arrives through `SELECTION_ENV`.
    """
    raw_selection = os.environ.get(SELECTION_ENV)
    selection = select_cases(raw_selection.split(",") if raw_selection else None)

    runner = pyperf.Runner(program_args=tuple(_program_args()))
    runner.parse_args(argv)
    run_cases(selection, runner)
    return 0


__all__ = ["DEFAULT_PROCESSES", "DEFAULT_SUMMARY", "SELECTION_ENV", "main", "worker_main"]
