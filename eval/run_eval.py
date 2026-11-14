"""Offline evaluation: score every recorded call through the real pipeline.

In: wav files plus `labels.csv` (file, label, scam_type, money_ask_s).
Out: `eval/results/table.md`, two risk-over-time plots, `failures.md`, and the raw
JSON behind each number.
It does not train, tune, or fetch anything. It runs after detection is frozen, once.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CALLS = ROOT / "eval" / "calls"
DEFAULT_RESULTS = ROOT / "eval" / "results"


@dataclass(frozen=True)
class CallLabel:
    """One row of labels.csv. `money_ask_s` is the second the ask happens, when known."""

    file: str
    label: int
    scam_type: str | None = None
    money_ask_s: float | None = None


def load_labels(path: Path) -> list[CallLabel]:
    """Read labels.csv. Blank rows are skipped; `label` must be 0 or 1."""
    rows: list[CallLabel] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            name = (raw.get("file") or "").strip()
            if not name:
                continue
            ask = (raw.get("money_ask_s") or "").strip()
            label = int((raw.get("label") or "").strip())
            if label not in (0, 1):
                raise ValueError(f"{name}: label must be 0 or 1, got {label!r}")
            rows.append(
                CallLabel(
                    file=name,
                    label=label,
                    scam_type=((raw.get("scam_type") or "").strip() or None),
                    money_ask_s=float(ask) if ask else None,
                )
            )
    return rows


def score_call(wav: Path, label: CallLabel) -> dict:
    """Run one recording through stt → scorer → alerts → danger, offline.

    Returns a dict with at least: `file`, `label`, `alert_t_s` (first alert, None if
    none), `alert_before_ask` (bool or None), `peak_score`, and the risk timeline.
    """
    raise NotImplementedError("evaluation lands in phase 6 — docs/SPEC.md §8")


def summarize(rows: list[dict]) -> dict:
    """Catch rate, false-alarm rate, median seconds to first alert, before-ask count.

    Every rate is returned with its denominator, because the write-up quotes counts.
    """
    raise NotImplementedError("evaluation lands in phase 6 — docs/SPEC.md §8")


def write_table(summary: dict, path: Path) -> Path:
    """Write table.md: test | metric | value | n | notes. One row per number."""
    raise NotImplementedError("evaluation lands in phase 6 — docs/SPEC.md §8")


def plot_call(timeline: list[dict], out_path: Path, title: str) -> Path:
    """One risk-over-time PNG: score on y, seconds on x, a line at 0.5 and 0.85."""
    raise NotImplementedError("evaluation lands in phase 6 — docs/SPEC.md §8")


def run(calls_dir: Path = DEFAULT_CALLS, results_dir: Path = DEFAULT_RESULTS) -> Path:
    """Score every labelled call, write table.md, the two plots and failures.md."""
    raise NotImplementedError("evaluation lands in phase 6 — docs/SPEC.md §8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score recorded calls through the real pipeline")
    parser.add_argument("--calls", type=Path, default=DEFAULT_CALLS)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args(argv)

    labels = load_labels(args.calls / "labels.csv")
    print(f"{len(labels)} labelled calls in {args.calls}")
    try:
        table = run(args.calls, args.results)
    except NotImplementedError as exc:
        print(f"not yet: {exc}")
        return 2
    print(f"wrote {table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
