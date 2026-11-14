"""Reads eval/calls/labels.csv.

In: the csv (file, label, scam_type, money_ask_s). Out: one `CallLabel` per row.
It does not open any audio and does not decide what a label means.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


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
