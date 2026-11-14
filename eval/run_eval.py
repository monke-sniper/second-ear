"""Offline evaluation: every recorded call in labels.csv through the real pipeline.

In: 16 kHz mono wavs plus `labels.csv` (file, label, scam_type, money_ask_s).
Out: `eval/results/calls.json`, `failures.md` and `table.md`. `--dry-run` writes nothing.
It does not train, tune, explain or push. It runs once, after detection is frozen, and
refuses to score the calls a second time. Run: python -m eval.run_eval
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from eval.labels import CallLabel, load_labels
from eval.metrics import RESULTS_SCHEMA, utc_now, write_json
from eval.replay import TAIL_MIN_S, Transcriber, WavFormatError, read_wav, replay_call
from eval.report import CAUGHT_RULE, TIME_NOTE, call_row, failures_markdown, snippet, summarize, verdict
from eval.scorer_id import describe_scorer, scorer_caveats
from eval.table import write_table
from server.scorer import RiskScorer

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CALLS = ROOT / "eval" / "calls"
DEFAULT_RESULTS = ROOT / "eval" / "results"
CALLS_NAME = "calls.json"
FAILURES_NAME = "failures.md"
WRONG = ("missed", "false_alarm")


class EvalStopped(RuntimeError):
    """The run cannot go on. The message is for the person at the keyboard."""


def score_calls(calls_dir: Path, labels: list[CallLabel], transcriber: Transcriber, scorer: RiskScorer) -> tuple[list[dict], dict[str, str]]:
    """Replay every labelled call. Returns one row per call, and a snippet per wrong call."""
    rows: list[dict] = []
    snippets: dict[str, str] = {}
    for label in labels:
        wav = Path(calls_dir) / label.file
        if not wav.is_file():
            raise EvalStopped(f"{label.file} is in labels.csv but not in {calls_dir}")
        replay = replay_call(read_wav(wav), transcriber, scorer)
        row = call_row(label, replay)
        if verdict(row) in WRONG:
            snippets[label.file] = snippet(row, replay.chunks)
        rows.append(row)
    return rows, snippets


def build_payload(rows: list[dict], scorer: RiskScorer, transcriber: Any) -> dict[str, Any]:
    """Everything calls.json holds: the scorer, the rules, each call and the totals."""
    info = describe_scorer(scorer)
    config = getattr(transcriber, "config", None)
    by_type: dict[str, dict[str, int]] = {}
    for row in rows:
        if row["label"] == 1:
            entry = by_type.setdefault(row["scam_type"] or "not labelled", {"n": 0, "caught": 0})
            entry["n"] += 1
            entry["caught"] += row["first_alert_level"] is not None
    return {
        "schema": RESULTS_SCHEMA,
        "system": info["name"],
        "created_utc": utc_now(),
        "scorer": info,
        "stt": {"model": getattr(config, "model_size", None), "device": getattr(transcriber, "device", None)},
        "rules": {"caught": CAUGHT_RULE, "alert_time": TIME_NOTE, "end_tail_min_s": TAIL_MIN_S},
        "calls": rows,
        "rows": summarize(rows, info["name"]),
        "by_type": by_type,
        "caveats": scorer_caveats(info),
    }


def run(calls_dir: Path, results_dir: Path, transcriber: Transcriber, scorer: RiskScorer, *, dry_run: bool = False, labels: list[CallLabel] | None = None) -> dict[str, Any]:
    """Score the labelled calls. Unless `dry_run`, write calls.json, failures.md, table.md."""
    target = Path(results_dir) / CALLS_NAME
    if not dry_run and target.exists():
        raise EvalStopped(f"{target} exists. The recorded calls are scored once; delete it yourself if a re-run is right.")
    listed = labels if labels is not None else load_labels(Path(calls_dir) / "labels.csv")
    if not listed:
        raise EvalStopped("labels.csv lists no calls, so there is nothing to score")
    rows, snippets = score_calls(calls_dir, listed, transcriber, scorer)
    payload = build_payload(rows, scorer, transcriber)
    if dry_run:
        return payload
    write_json(payload, target)
    text = failures_markdown(rows, snippets, payload["system"], payload["caveats"])
    (Path(results_dir) / FAILURES_NAME).write_text(text, encoding="utf-8")
    write_table(results_dir)
    return payload


def show(payload: dict[str, Any]) -> None:
    """Print the facts per call and the totals. Never a transcript."""
    print(f"scorer: {payload['scorer']['name']}   stt: {payload['stt']}")
    for row in payload["calls"]:
        print(
            f"{row['file']}: label {row['label']}, {row['duration_s']} s, first alert "
            f"{row['first_alert_level']} at {row['first_alert_t_s']} s, scam alert at {row['scam_alert_t_s']} s, "
            f"danger {row['danger_fired']} at {row['danger_t_s']} s, before ask {row['alerted_before_ask']}, "
            f"peak {row['peak_score']}, tail {row['tail_s']} s -> {verdict(row)}"
        )
    for row in payload["rows"]:
        print(f"  {row['metric']:<32} {'n/a' if row['value'] is None else row['value']}  n={row['n']}")
    for note in payload["caveats"]:
        print(f"note: {note}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score recorded calls through the real pipeline")
    parser.add_argument("--calls", type=Path, default=DEFAULT_CALLS)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--dry-run", action="store_true", help="print the results, write nothing")
    parser.add_argument("--table-only", action="store_true", help="rebuild table.md from the results files")
    parser.add_argument("--file", type=Path, help="one wav outside labels.csv; always a dry run")
    parser.add_argument("--label", type=int, choices=(0, 1), help="its label, with --file")
    parser.add_argument("--money-ask-s", type=float, help="its money ask second, with --file")
    args = parser.parse_args(argv)
    if args.table_only:
        print(f"wrote {write_table(args.results)}")
        return 0
    if args.file is not None and args.label is None:
        parser.error("--file needs --label")
    from server.scorer import load_app_scorer
    from server.stt import load_transcriber

    one = None if args.file is None else [CallLabel(args.file.name, args.label, None, args.money_ask_s)]
    calls_dir = args.calls if args.file is None else args.file.parent
    try:
        payload = run(calls_dir, args.results, load_transcriber(), load_app_scorer(), dry_run=args.dry_run or one is not None, labels=one)
    except (EvalStopped, WavFormatError) as exc:
        print(f"stopped: {exc}")
        return 2
    show(payload)
    print("dry run: nothing written" if args.dry_run or one is not None else f"wrote {args.results / CALLS_NAME}, {FAILURES_NAME} and table.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
