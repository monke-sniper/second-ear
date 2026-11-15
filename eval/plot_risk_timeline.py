"""Draws the README chart of the risk score over time for two recorded calls.

In: `eval/results/calls.json`, and no other file. Out: `docs/img/risk-timeline.png`.
It does not score a call, read audio or a transcript, or write to `eval/results/`, so no
word or number spoken on a call can reach the image. Run: python -m eval.plot_risk_timeline
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CALLS_JSON = ROOT / "eval" / "results" / "calls.json"
DEFAULT_OUT = ROOT / "docs" / "img" / "risk-timeline.png"

SCAM_FILE = "12_prize_code.wav"
LEGIT_FILE = "01_pharmacy.wav"
# The alert thresholds the recorded calls were scored with (docs/SPEC.md §2). calls.json
# does not carry them, and this script reads nothing else, so they are written out here.
CAUTION_LINE = 0.5
SCAM_LINE = 0.85

# docs/design/tokens.json. The legitimate call's line is one step brighter than
# color.calm.base, which reads as gray at the weight of a line.
SURFACE = "#F8FAFC"
INK = "#0F172A"
MUTED = "#475569"
RULE = "#64748B"
BORDER = "#CBD5E1"
SCAM_RED = "#B91C1C"
CALM_TEAL = "#0D9488"
FONT = "Segoe UI"  # the app's font on Windows; matplotlib falls back to its own elsewhere

Call = dict[str, Any]


def load_pair(calls_json: Path) -> tuple[Call, Call]:
    """The scam call and the legitimate call, checked for what the chart says about them."""
    data = json.loads(calls_json.read_text(encoding="utf-8"))
    by_file = {call["file"]: call for call in data["calls"]}
    scam, legit = by_file[SCAM_FILE], by_file[LEGIT_FILE]
    if scam["label"] != 1 or legit["label"] != 0:
        raise ValueError("the two calls are not one scam call and one legitimate call")
    if scam["scam_alert_t_s"] is None or not scam["danger_fired"]:
        raise ValueError(f"{SCAM_FILE} has no scam alert or no code warning to mark")
    if legit["first_alert_level"] is not None or legit["danger_fired"]:
        raise ValueError(f"{LEGIT_FILE} raised an alert or a warning; the chart says it did not")
    return scam, legit


def score_at(call: Call, t_s: float) -> float:
    """The score of the chunk that ended at `t_s`."""
    for point in call["timeline"]:
        if point["t_s"] == t_s:
            return float(point["score"])
    raise ValueError(f"no chunk ends at {t_s} s in {call['file']}")


def draw_thresholds(ax: Axes, x_right: float) -> None:
    """The two alert lines, dashed because they are thresholds and not a grid."""
    for level in (CAUTION_LINE, SCAM_LINE):
        ax.axhline(level, color=RULE, linewidth=0.9, linestyle=(0, (5, 4)), zorder=1)
    ax.axhline(1.0, color=BORDER, linewidth=0.7, zorder=1)
    notes = (
        (SCAM_LINE, f"Scam line, {SCAM_LINE:g}", "two chunks in a row above it raise the scam alert"),
        (CAUTION_LINE, f"Caution line, {CAUTION_LINE:g}", "caution when the smoothed score reaches it"),
    )
    for level, name, rule in notes:
        ax.text(x_right, level - 0.03, name, ha="right", va="top", fontsize=10,
                fontweight="semibold", color=INK)
        ax.text(x_right, level - 0.105, rule, ha="right", va="top", fontsize=9.5, color=MUTED)


def draw_series(ax: Axes, call: Call, color: str, marker: str, size: float, zorder: int) -> None:
    """One call: a dot per chunk at the time the chunk ended, joined by a line."""
    xs = [point["t_s"] for point in call["timeline"]]
    ys = [point["score"] for point in call["timeline"]]
    ax.plot(xs, ys, color=color, linewidth=1.7, marker=marker, markersize=size,
            markerfacecolor=color, markeredgecolor=SURFACE, markeredgewidth=1.0,
            solid_capstyle="round", solid_joinstyle="round", zorder=zorder, clip_on=False)


def draw_moments(ax: Axes, scam: Call) -> None:
    """The scam alert and the code warning, at the times calls.json gives for them."""
    moments = (("Scam alert", scam["scam_alert_t_s"]), ("Code warning", scam["danger_t_s"]))
    for name, t_s in moments:
        score = score_at(scam, t_s)
        ax.vlines(t_s, -0.05, score, color=INK, linewidth=0.9, zorder=2)
        ax.plot([t_s], [score], marker="o", markersize=11.5, markerfacecolor="none",
                markeredgecolor=INK, markeredgewidth=1.3, zorder=5, clip_on=False)
        ax.text(t_s + 1.3, 0.70, name, ha="left", va="center", fontsize=10.5,
                fontweight="semibold", color=INK)
        ax.text(t_s + 1.3, 0.625, f"at {t_s:g} s", ha="left", va="center", fontsize=9.5, color=MUTED)


def style_axes(ax: Axes, x_max: float) -> None:
    ax.set_xlim(-1.5, x_max + 3)
    ax.set_ylim(-0.05, 1.1)
    ax.set_yticks([0, CAUTION_LINE, SCAM_LINE, 1.0], labels=["0", f"{CAUTION_LINE:g}", f"{SCAM_LINE:g}", "1"])
    ax.set_xticks(range(0, int(x_max) + 1, 20))
    ax.tick_params(axis="both", length=0, labelsize=9.5, labelcolor=MUTED, pad=6)
    ax.set_xlabel("Seconds into the call", fontsize=10, color=MUTED, labelpad=6)
    ax.set_ylabel("Risk score", fontsize=10, color=MUTED, labelpad=6)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BORDER)
    ax.spines["bottom"].set_linewidth(0.8)


def draw_header(fig: Figure) -> None:
    """Title, one line on how to read a dot, and the legend with a shape per call."""
    keys = (
        (SCAM_RED, "o", 6.2, "Call 12: a prize scam"),
        (CALM_TEAL, "s", 5.4, "Call 01: a legitimate pharmacy call"),
    )
    handles = [
        Line2D([], [], color=color, linewidth=1.7, marker=marker, markersize=size,
               markeredgecolor=SURFACE, markeredgewidth=1.0, label=label)
        for color, marker, size, label in keys
    ]
    legend = fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.02, 0.842), ncol=2,
                        frameon=False, fontsize=10, handlelength=2.3, columnspacing=2.2,
                        handletextpad=0.6, borderaxespad=0, borderpad=0)
    for text in legend.get_texts():
        text.set_color(INK)
    fig.text(0.02, 0.945, "Risk score during two recorded calls", ha="left", va="center",
             fontsize=13.5, fontweight="bold", color=INK)
    fig.text(0.02, 0.882, "Each dot is one chunk of audio, scored when the chunk ends.",
             ha="left", va="center", fontsize=10, color=MUTED)


def draw(calls_json: Path = CALLS_JSON, out: Path = DEFAULT_OUT) -> Path:
    """Read the two calls, draw the chart and write the PNG. Returns the path written."""
    scam, legit = load_pair(calls_json)
    x_max = max(scam["duration_s"], legit["duration_s"])

    plt.rcParams["font.family"] = FONT
    fig = plt.figure(figsize=(8.4, 4.6), dpi=200, facecolor=SURFACE)
    ax = fig.add_axes((0.085, 0.135, 0.895, 0.615), facecolor=SURFACE)
    style_axes(ax, x_max)
    draw_thresholds(ax, x_max + 1.5)
    draw_series(ax, legit, CALM_TEAL, "s", 5.4, zorder=3)
    draw_series(ax, scam, SCAM_RED, "o", 6.2, zorder=4)
    draw_moments(ax, scam)
    # Short labels at the line ends; the legend carries the full names.
    last = scam["timeline"][-1]
    ax.text(last["t_s"] + 1.8, last["score"], "Prize scam", ha="left", va="center", fontsize=10, color=INK)
    ax.text(legit["timeline"][-1]["t_s"], 0.05, "Pharmacy call", ha="right", va="bottom", fontsize=10, color=INK)
    draw_header(fig)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draw the risk timeline chart from eval/results/calls.json")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to write the PNG")
    args = parser.parse_args(argv)
    print(f"wrote {draw(out=args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
