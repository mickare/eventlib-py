# Copyright 2026 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Graph rendering of a benchmark summary.

One figure, two panels, both sharing the case axis:

1. **Cost per case** — reference vs. library, log scale (the cases span several orders of
   magnitude).
2. **Overhead factor** — ``library / reference`` per case, with a line at ``1.0`` (parity)
   and a line at the overall score. This is the number the score is the median of.

Cases are ordered by overhead, worst first, so the panel reads as a ranking.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .errors import BenchmarkError

if TYPE_CHECKING:  # pragma: no cover - imported lazily so `run` stays fast
    from .suite import SuiteResult

REFERENCE_COLOR = "#B8B8B8"
LIBRARY_COLOR = "#4C72B0"
DIAGNOSTIC_COLOR = "#A8C4E0"
SCORE_COLOR = "#C44E52"


def _short_label(case_id: str) -> str:
    """Drop the group prefix; the group is already implied by the case order."""
    return case_id.split(".", 1)[-1]


def _draw_cost_panel(ax: Any, cases: list[Any], positions: list[int]) -> None:
    """Draw the absolute cost of both sides on a log scale."""
    bar_height = 0.4
    ax.barh(
        [p + bar_height / 2 for p in positions],
        [max(item.reference, 1e-12) for item in cases],
        height=bar_height,
        label="reference (plain Python)",
        color=REFERENCE_COLOR,
    )
    ax.barh(
        [p - bar_height / 2 for p in positions],
        [max(item.library, 1e-12) for item in cases],
        height=bar_height,
        label="eventlib",
        color=LIBRARY_COLOR,
    )
    ax.set_xscale("log")
    ax.set_xlabel("time per operation (log scale)")
    ax.set_title("Cost per case")
    ax.set_yticks(positions, [_short_label(item.case.id) for item in cases])
    ax.invert_yaxis()
    ax.grid(True, which="both", axis="x", linestyle=":", linewidth=0.6)
    ax.legend(loc="lower right", frameon=False)


def _draw_overhead_panel(ax: Any, cases: list[Any], positions: list[int], score: float) -> None:
    """Draw the per-case overhead factor with its spread and the score line."""
    from matplotlib.patches import Patch  # pylint: disable=import-outside-toplevel

    ratios = [item.ratio for item in cases]
    errors = [item.ratio_stdev for item in cases]
    has_errors = any(error is not None for error in errors)

    # Diagnostic cases are drawn faded: they are measured but excluded from the score.
    ax.barh(
        positions,
        ratios,
        height=0.6,
        color=[LIBRARY_COLOR if item.scored else DIAGNOSTIC_COLOR for item in cases],
    )
    if has_errors:
        ax.errorbar(
            ratios,
            positions,
            xerr=[error or 0.0 for error in errors],
            fmt="none",
            ecolor="#333333",
            elinewidth=1.0,
            capsize=3,
        )

    ax.axvline(1.0, color="black", linewidth=1.0, linestyle="--", label="parity")
    ax.axvline(score, color=SCORE_COLOR, linewidth=1.2, label=f"score {score:.2f}x")
    ax.set_xlabel("library / reference (log scale)")
    ax.set_title("Overhead factor (±1σ)" if has_errors else "Overhead factor")
    ax.grid(True, which="both", axis="x", linestyle=":", linewidth=0.6)

    # A single diagnostic outlier can be an order of magnitude above the rest, so the axis
    # is logarithmic; a linear one would squash every other bar into the left edge.
    ends = [ratio + (error or 0.0) for ratio, error in zip(ratios, errors)]
    ax.set_xscale("log")
    ax.set_xlim(min(0.9, min(ratios) * 0.9), max(ends) * 2.0)
    for position, end, ratio in zip(positions, ends, ratios):
        ax.text(end * 1.08, position, f"{ratio:.2f}x", va="center", fontsize=8)

    handles, labels = ax.get_legend_handles_labels()
    if any(not item.scored for item in cases):
        handles.append(Patch(color=DIAGNOSTIC_COLOR))
        labels.append("diagnostic (not scored)")
    ax.legend(handles, labels, loc="lower right", frameon=False)


def render_suite(result: "SuiteResult", output: Path | None = None) -> None:
    """
    Render the summary.

    :param result: Summary to render.
    :param output: If given, the figure is written there. Otherwise an interactive window
        is opened (``plt.show()``).
    """
    from matplotlib import pyplot as plt  # pylint: disable=import-outside-toplevel

    cases = sorted(result.results, key=lambda item: item.ratio, reverse=True)
    if not cases:
        raise BenchmarkError("nothing to render: the summary contains no cases")

    positions = list(range(len(cases)))
    fig, (ax_cost, ax_ratio) = plt.subplots(
        ncols=2,
        figsize=(14, max(4.0, 0.36 * len(cases))),
        sharey=True,
        gridspec_kw={"width_ratios": [2.0, 1.0]},
    )
    fig.suptitle(f"eventlib-py — overall score {result.score:.2f}x", fontsize=13)

    _draw_cost_panel(ax_cost, cases, positions)
    _draw_overhead_panel(ax_ratio, cases, positions, result.score)

    fig.tight_layout()

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, dpi=150, bbox_inches="tight")
        print(f"Figure written to {output}")
        plt.close(fig)
    else:
        plt.show()


__all__ = ["render_suite"]
