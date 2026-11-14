"""The metric helpers the notebooks use, so every results file has one shape.

In: labels and predictions. Out: counts, precision / recall / F1, and table-ready rows.
It does not score, load data or pick a threshold.

`prefix_at`, `binary_metrics`, `rounded`, `metric_rows` and `utc_now` are copied from the
shared helpers cell of ml/train_risk_model.ipynb and ml/baselines.ipynb. Change those first.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

RESULTS_SCHEMA = "second-ear/results-v1"
METRIC_NAMES = ("precision", "recall", "f1")
CONFUSION_KEYS = ("tp", "fp", "fn", "tn")


def prefix_at(text: str, percent: int) -> str:
    """The first `percent` % of the text's words, rounded up, never fewer than one word."""
    words = text.split()
    keep = max(1, (len(words) * percent + 99) // 100)
    return " ".join(words[:keep])


def binary_metrics(labels: Sequence[int], predictions: Sequence[int]) -> dict:
    """Precision, recall and F1 for the scam class, with the counts behind them.

    A metric with a zero denominator is None, not 0, so no table can show a made-up number.
    """
    pairs = list(zip(labels, predictions))
    tp = sum(1 for label, guess in pairs if label == 1 and guess == 1)
    fp = sum(1 for label, guess in pairs if label == 0 and guess == 1)
    fn = sum(1 for label, guess in pairs if label == 1 and guess == 0)
    tn = sum(1 for label, guess in pairs if label == 0 and guess == 0)
    return {
        "n": len(pairs),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
    }


def correct_by(rows: Sequence[dict], predictions: Sequence[int], field: str) -> dict:
    """Per value of `field`: how many rows there are and how many were labelled correctly."""
    totals = Counter(row[field] for row in rows)
    correct = Counter(row[field] for row, guess in zip(rows, predictions) if guess == row["label"])
    return {kind: {"n": totals[kind], "correct": correct[kind]} for kind in sorted(totals)}


def rounded(value: float | None) -> float | None:
    """Four decimals for the results file; None stays None."""
    return None if value is None else round(value, 4)


def metric_rows(test: str, metrics: dict, context: str) -> list[dict]:
    """Table-ready rows for one test set: test, metric, value, n, notes (docs/SPEC.md §8).

    n is each metric's own denominator: dialogues flagged as scam for precision, scam
    dialogues for recall, every dialogue scored for F1.
    """
    counts = f"tp={metrics['tp']} fp={metrics['fp']} fn={metrics['fn']} tn={metrics['tn']}"
    denominators = {
        "precision": (metrics["tp"] + metrics["fp"], "dialogues flagged as scam"),
        "recall": (metrics["tp"] + metrics["fn"], "scam dialogues"),
        "f1": (metrics["n"], "dialogues scored"),
    }
    rows = []
    for name in METRIC_NAMES:
        n, meaning = denominators[name]
        notes = f"n = {meaning}; {metrics['n']} scored in all; {counts}; {context}"
        rows.append(
            {"test": test, "metric": name, "value": rounded(metrics[name]), "n": n, "notes": notes}
        )
    return rows


def write_json(payload: Any, path: Path) -> Path:
    """Write one file as indented JSON, creating its folder, and return its path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def file_sha256(path: Path) -> str:
    """sha256 of a file, read in blocks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    """Current UTC time, to the second, for a results file."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
