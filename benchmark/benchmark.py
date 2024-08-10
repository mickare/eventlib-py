#!/usr/bin/env python3
# Copyright 2024 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Benchmark of the event system.

The reference implementation is the following::

    async def run_reference(event: B):
        async with async_context_func(event), AsyncContextClass(event):
            with sync_context_func(event), SyncContextClass(event):
                sync_func0(event)
                sync_func1(event)
                await async_func(event)

"""
import argparse
import asyncio
import dataclasses
import functools
import textwrap
import time
from typing import Callable, Protocol

import pandas
import tqdm
from matplotlib import pyplot as plt
from matplotlib.ticker import PercentFormatter

from benchmark.cases import case_all
from eventlib import Event, EventSystem


class BenchmarkCase(Protocol):
    """Protocol interface for a benchmark case."""

    @staticmethod
    def build(system: EventSystem) -> None:
        """Build the event system."""

    @staticmethod
    def new_event() -> Event:
        """Get the event."""

    @staticmethod
    async def run_reference(event: Event) -> None:
        """Run the reference implementation."""

    @staticmethod
    async def run_eventlib(system: EventSystem, event: Event) -> None:
        """Run the event library implementation."""


BENCHMARK_CASES: dict[str, BenchmarkCase] = {"all": case_all}  # type: ignore
"""Benchmark cases available."""


async def _timeit(iterations: int, func: Callable, *args, **kwargs) -> float:
    """Measure the time of an async function."""
    if iterations <= 0:
        return 0.0
    start = time.perf_counter()
    for _ in range(iterations):
        await func(*args, **kwargs)
    return time.perf_counter() - start


def format_si_unit(value: int | float, suffix: str, decimals: int = 0) -> str:
    """Format a number with SI units."""
    for unit in ["", "k", "M", "G", "T", "P", "E", "Z"]:
        if value < 1e3:
            break
        value /= 1e3
    if value < 1:
        for unit in ["", "m", "μ", "n", "p", "f"]:
            if value >= 1:
                break
            value *= 1e3
    return f"{value:.{decimals}f}{unit}{suffix}"


@dataclasses.dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Benchmark result."""

    iterations: int
    time_ref: float
    time_lib: float
    time_lib_init: float

    @property
    def overhead_factor(self) -> float:
        """The measured overhead factor of the eventlib package."""
        return self.time_lib / self.time_ref

    def __str__(self):
        time_ref_per_it = format_si_unit(self.time_ref / self.iterations, "s")
        time_lib_per_it = format_si_unit(self.time_lib / self.iterations, "s")
        time_lib_init_fmt = format_si_unit(self.time_lib_init, "s")
        return textwrap.dedent(
            f"""Benchmark result for {self.iterations} iterations:
            - Reference time: {self.time_ref:>5.3f}s (~{time_ref_per_it:>5})
            - Library time:   {self.time_lib:>5.3f}s (~{time_lib_per_it:>5}) x{self.overhead_factor:.2f}
            - Library init:   {time_lib_init_fmt:>5}
            """
        )


def benchmark(case: BenchmarkCase, iterations: int) -> BenchmarkResult:
    """Benchmark a single case with the amount of iterations."""
    # Measure event library - initialization
    start = time.perf_counter()
    system = EventSystem()
    case.build(system)
    time_lib_init = time.perf_counter() - start

    event = case.new_event()
    time_ref = asyncio.run(_timeit(iterations, case.run_reference, event))
    time_lib = asyncio.run(_timeit(iterations, case.run_eventlib, system, event))

    return BenchmarkResult(iterations, time_ref, time_lib, time_lib_init)


def dataframe_from_results(results: list[BenchmarkResult], repeat: int, warmup: int) -> pandas.DataFrame:
    """Create a DataFrame from the benchmark results."""
    df = pandas.DataFrame(
        {
            "Iterations": [b.iterations for b in results],
            "Reference": [b.time_ref for b in results],
            "Library": [b.time_lib for b in results],
            "Library Init": [b.time_lib_init for b in results],
            "Factor": [b.time_lib / b.time_ref for b in results],
        }
    )
    df.attrs["repeat"] = repeat
    df.attrs["warmup"] = warmup
    return df


def benchmark_single(case: BenchmarkCase, iterations: int, warmup: int, repeat: int) -> pandas.DataFrame:
    """Run a single benchmark."""
    results = []
    # Warmup
    benchmark(case, warmup)
    # Benchmark
    with tqdm.tqdm(total=repeat * iterations) as pbar:
        for _ in range(repeat):
            results.append(benchmark(case, iterations))
            pbar.update(iterations)
    return dataframe_from_results(results, repeat, warmup)


def benchmark_range(case: BenchmarkCase, repeat=100, warmup=10_000, iterations_power: int = 18) -> pandas.DataFrame:
    """Run a range of benchmarks."""
    results: list[BenchmarkResult] = []
    total = repeat * sum(2**p for p in range(1, iterations_power + 1))
    # Warmup
    benchmark(case, warmup)
    # Benchmark
    with tqdm.tqdm(total=total) as pbar:
        for p in range(1, iterations_power + 1):
            for _ in range(repeat):
                result = benchmark(case, 2**p)
                results.append(result)
                pbar.update(result.iterations)
    return dataframe_from_results(results, repeat, warmup)


def benchmark_render(frame: pandas.DataFrame):
    """Render the benchmark results."""
    fig, (ax0, ax1) = plt.subplots(nrows=2)  # type: ignore
    fig.suptitle("Event System Benchmark")

    ax0.set_ylabel("Call Time (μs)")
    ax0.set_xscale("log", base=2)

    ax1.set_ylabel("Overhead")
    ax1.set_xscale("log", base=2)
    ax1.set_ylim(0.95, 1.3)
    ax1.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))

    # Normalize to microseconds
    df = frame.copy()
    df["Reference"] *= 1e6 / df["Iterations"]
    df["Library"] *= 1e6 / df["Iterations"]

    values = df.groupby("Iterations").quantile(0.50)
    values.plot(y="Reference", ax=ax0, label="Reference")
    values.plot(y="Library", ax=ax0, label="Library")
    values.plot(y="Factor", ax=ax1, label="Factor")

    ax0.grid(True, which="both", axis="y", linestyle=":")
    ax1.grid(True, which="both", axis="y", linestyle=":")

    plt.show()


def benchmark_cli():
    """Command line for the benchmark."""
    parser = argparse.ArgumentParser()
    cmd_parser = parser.add_subparsers(title="Commands", dest="command")

    cmd_run = cmd_parser.add_parser("run", help="Run a single benchmark")
    cmd_run.add_argument("-c", "--case", type=str, default="all")
    cmd_run.add_argument("-i", "--iterations", type=int, default=10_000)
    cmd_run.add_argument("-r", "--repeat", type=int, default=100)
    cmd_run.add_argument("-w", "--warmup", type=int, default=10_000)

    cmd_range = cmd_parser.add_parser("range", help="Run many benchmarks on a range of iterations")
    cmd_range.add_argument("-c", "--case", type=str, default="all")
    cmd_range.add_argument("-r", "--repeat", type=int, default=100)
    cmd_range.add_argument("-w", "--warmup", type=int, default=10_000)
    cmd_range.add_argument("--iterations-power", type=int, default=18)
    cmd_range.add_argument("-f", "--file", type=str, default="benchmark_ranged.json")
    cmd_range.add_argument("--no-render", action="store_false", dest="render")

    cmd_render = cmd_parser.add_parser("render", help="Render the benchmark results")
    cmd_render.add_argument("-f", "--file", type=str, default="benchmark_ranged.json")

    args = parser.parse_args()
    command = args.command or "simple"

    match command:
        case "range":
            case = BENCHMARK_CASES[args.case]
            df = benchmark_range(case, args.repeat, args.warmup, iterations_power=args.iterations_power)
            df.to_json(args.file)
            if args.render:
                benchmark_render(df)
        case "render":
            df = pandas.read_json(args.file)
            assert isinstance(df, pandas.DataFrame)
            benchmark_render(df)
        case "run":
            case = BENCHMARK_CASES[args.case]
            iterations = args.iterations
            df = benchmark_single(case, iterations, args.warmup, args.repeat)
            print(f"Results for benchmark '{case.__name__}' and {args.iterations} iterations:")
            result = df[["Reference", "Library", "Library Init", "Factor"]].quantile([0.5, 0.9, 0.99])

            _format_si_unit = functools.partial(format_si_unit, suffix="s", decimals=3)
            result["Reference"] = (result["Reference"] / iterations).apply(_format_si_unit)
            result["Library"] = (result["Library"] / iterations).apply(_format_si_unit)
            result["Library Init"] = result["Library Init"].apply(_format_si_unit)
            print(result.to_markdown(floatfmt=".2f", colalign=("left", "right", "right", "right", "right")))


if __name__ == "__main__":
    benchmark_cli()
