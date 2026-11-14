"""Scores the Gemini held-out set with the app's scorer and with the keyword baseline.

In: eval/heldout/gemini.jsonl. Out: eval/results/heldout.json, rows in the same shape as
baselines.json, on the full text and on the first 40 % of its words.
It does not generate, tune or pick a threshold: scam is score >= 0.5 for the app scorer,
any listed phrase for the baseline. Run: python -m eval.score_heldout
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from eval import keyword_baseline
from eval.metrics import (
    CONFUSION_KEYS,
    RESULTS_SCHEMA,
    binary_metrics,
    correct_by,
    file_sha256,
    metric_rows,
    prefix_at,
    utc_now,
    write_json,
)
from eval.scorer_id import describe_scorer, scorer_caveats
from server.config import ROOT
from server.scorer import RiskScorer, load_app_scorer

DEFAULT_SET = ROOT / "eval" / "heldout" / "gemini.jsonl"
DEFAULT_OUT = ROOT / "eval" / "results" / "heldout.json"
FULL_TEST = "gemini_heldout_full"
EARLY_PERCENT = 40
EARLY_TEST = f"gemini_heldout_prefix{EARLY_PERCENT}"
# The model's own rule (ml/README.md), which is also the caution threshold in SPEC §2.
THRESHOLD = 0.5
BASELINE = "keyword"
BRIEF_CAVEAT = (
    "The generator brief was written by the same assistant that wrote the stand-in's phrase "
    "list. The brief names kinds of call only, and the transcripts are Gemini's wording."
)
RERUN_CAVEAT = "A re-run replaces this file; `scorer` says which scorer made the app rows."


def load_heldout(path: Path) -> list[dict]:
    """Read the set. Every row needs id, label 0/1, type, opening and text."""
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        if row["label"] not in (0, 1) or not row["text"].strip():
            raise ValueError(f"{row.get('id')}: needs label 0 or 1 and some text")
    return [{**row, "text": " ".join(row["text"].split())} for row in rows]


def score_system(name: str, rows: list[dict], predict: Callable[[str], int], context: str) -> dict:
    """Run one system over both tests. Returns its table rows and the counts behind them."""
    labels = [row["label"] for row in rows]
    tests = {
        FULL_TEST: ([row["text"] for row in rows], context),
        EARLY_TEST: ([prefix_at(row["text"], EARLY_PERCENT) for row in rows], f"first {EARLY_PERCENT} % of words; {context}"),
    }
    out: dict[str, Any] = {"rows": [], "confusion": {}, "by_type": {}, "by_opening": {}}
    for test, (texts, notes) in tests.items():
        predictions = [predict(text) for text in texts]
        metrics = binary_metrics(labels, predictions)
        out["rows"] += [{"system": name, **row} for row in metric_rows(test, metrics, notes)]
        out["confusion"][test] = {key: metrics[key] for key in CONFUSION_KEYS}
        out["by_type"][test] = correct_by(rows, predictions, "type")
        out["by_opening"][test] = correct_by(rows, predictions, "opening")
    return out


def build_payload(rows: list[dict], scorer: RiskScorer, set_path: Path) -> dict:
    """Everything heldout.json holds. No transcript text goes in it."""
    info = describe_scorer(scorer)
    app_name = info["name"]
    positive = "scam is the positive class"
    systems = {
        app_name: score_system(app_name, rows, lambda text: int(scorer.score(text) >= THRESHOLD), f"{positive}; app scorer {app_name}, score >= {THRESHOLD}"),
        BASELINE: score_system(BASELINE, rows, keyword_baseline.predict, f"{positive}; any listed phrase present"),
    }
    meta_path = Path(set_path).with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    labels = Counter(row["label"] for row in rows)
    return {
        "schema": RESULTS_SCHEMA,
        "systems": list(systems),
        "created_utc": utc_now(),
        "heldout": {
            "file": "eval/heldout/gemini.jsonl",
            "sha256": file_sha256(set_path),
            "rows": len(rows),
            "scam": labels[1],
            "legitimate": labels[0],
            "generator_model": meta.get("generator", {}).get("model"),
            "brief_sha256": meta.get("brief_sha256"),
        },
        "preprocessing": {
            "text": "as written by the generator, whitespace collapsed; no speaker labels to remove",
            "app_scorer": "given the text as the live app would be; it does its own cleaning",
            "prefix": f"first {EARLY_PERCENT} % of the words, rounded up",
        },
        "threshold": THRESHOLD,
        "scorer": info,
        "rule": keyword_baseline.RULE,
        "keywords": list(keyword_baseline.KEYWORDS),
        "rows": [row for system in systems.values() for row in system["rows"]],
        "confusion": {name: system["confusion"] for name, system in systems.items()},
        "by_type": {name: system["by_type"] for name, system in systems.items()},
        "by_opening": {name: system["by_opening"] for name, system in systems.items()},
        "caveats": scorer_caveats(info) + [BRIEF_CAVEAT, RERUN_CAVEAT],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score the Gemini held-out set")
    parser.add_argument("--set", type=Path, default=DEFAULT_SET, dest="set_path")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if not args.set_path.is_file():
        print(f"{args.set_path} does not exist. Run python -m eval.make_heldout first.")
        return 2
    payload = build_payload(load_heldout(args.set_path), load_app_scorer(), args.set_path)
    write_json(payload, args.out)
    for row in payload["rows"]:
        value = "n/a" if row["value"] is None else f"{row['value']:.4f}"
        print(f"{row['system']:<18} {row['test']:<26} {row['metric']:<10} {value}  n={row['n']}")
    print(f"scorer: {payload['scorer']['name']}; wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
