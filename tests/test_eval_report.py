"""The recorded-call run: per-call rows, totals with their n, failures.md and table.md.

Four made-up recordings go through the real chunker and session with a fake Whisper and a
fake scorer. Digits in the fake speech are invented; assertions about them are booleans.
"""

from __future__ import annotations

import json

import pytest

from eval.report import summarize
from eval.run_eval import CALLS_NAME, FAILURES_NAME, EvalStopped, run
from eval.table import TABLE_NAME, table_markdown
from tests.test_eval_replay import SPOKEN, Says, write_wav

LABELS = "file,label,scam_type,money_ask_s\nscam.wav,1,grandparent,6\nok.wav,0,,\nfalse.wav,0,,\nmissed.wav,1,prize,4\n"
SPEECH = [
    "hi grandma", "buy gift cards", "read me 4 1 5 9 2 6",  # scam.wav
    "your refill is ready", "pick it up today", "goodbye",  # ok.wav
    "we sell gift baskets", "gift wrap is free", "bye",  # false.wav
    "hello there", "send it to 5 5 5 0 1 0 0 now", "ok then",  # missed.wav
]


class FlagsGift:
    name = "fake-scorer"

    def score(self, transcript: str) -> float:
        return 0.95 if "gift" in transcript else 0.1


@pytest.fixture()
def calls_dir(tmp_path):
    folder = tmp_path / "calls"
    folder.mkdir()
    for name in ("scam.wav", "ok.wav", "false.wav", "missed.wav", "not_listed.wav"):
        write_wav(folder / name, SPOKEN * 3)
    (folder / "labels.csv").write_text(LABELS, encoding="utf-8")
    return folder


def metric(payload: dict, name: str) -> dict:
    return next(row for row in payload["rows"] if row["metric"] == name)


def test_run_scores_only_the_listed_calls_and_writes_the_three_files(calls_dir, tmp_path):
    results = tmp_path / "results"
    whisper = Says(SPEECH)

    payload = run(calls_dir, results, whisper, FlagsGift())

    assert len(whisper.calls) == 12  # four listed calls of three chunks; not_listed.wav is left alone
    assert sorted(path.name for path in results.iterdir()) == [CALLS_NAME, FAILURES_NAME, TABLE_NAME]
    calls = {row["file"]: row for row in payload["calls"]}
    assert calls["scam.wav"]["first_alert_level"] in ("caution", "scam")
    assert calls["scam.wav"]["alerted_before_ask"] is True and calls["scam.wav"]["danger_fired"] is True
    assert calls["ok.wav"]["first_alert_level"] is None and calls["ok.wav"]["alerted_before_ask"] is None
    assert calls["false.wav"]["first_alert_level"] is not None
    assert calls["missed.wav"]["first_alert_level"] is None and calls["missed.wav"]["alerted_before_ask"] is False

    assert (metric(payload, "catch_rate")["value"], metric(payload, "catch_rate")["n"]) == (0.5, 2)
    assert (metric(payload, "false_alarm_rate")["value"], metric(payload, "false_alarm_rate")["n"]) == (0.5, 2)
    median = metric(payload, "median_seconds_to_first_alert")
    assert (median["value"], median["n"]) == (calls["scam.wav"]["first_alert_t_s"], 1)
    assert (metric(payload, "alerted_before_money_ask")["value"], metric(payload, "alerted_before_money_ask")["n"]) == (0.5, 2)
    assert payload["scorer"]["name"] == "fake-scorer" and payload["system"] == "fake-scorer"
    assert payload["by_type"] == {"grandparent": {"n": 1, "caught": 1}, "prize": {"n": 1, "caught": 0}}


def test_results_hold_no_transcript_and_failures_hold_no_digit(calls_dir, tmp_path):
    results = tmp_path / "results"
    run(calls_dir, results, Says(SPEECH), FlagsGift())

    assert "grandma" not in (results / CALLS_NAME).read_text(encoding="utf-8")
    failures = (results / FAILURES_NAME).read_text(encoding="utf-8")
    heard = [line for line in failures.splitlines() if line.startswith("- Heard:")]
    assert "missed.wav" in failures and "false.wav" in failures and "ok.wav" not in failures
    assert len(heard) == 2 and all("[number]" in line or "gift" in line for line in heard)
    assert not any(character.isdigit() for line in heard for character in line)


def test_a_dry_run_writes_nothing(calls_dir, tmp_path):
    results = tmp_path / "results"
    results.mkdir()

    payload = run(calls_dir, results, Says(SPEECH), FlagsGift(), dry_run=True)

    assert len(payload["calls"]) == 4 and list(results.iterdir()) == []


def test_the_calls_are_scored_once(calls_dir, tmp_path):
    results = tmp_path / "results"
    run(calls_dir, results, Says(SPEECH), FlagsGift())
    before = (results / CALLS_NAME).read_bytes()

    with pytest.raises(EvalStopped):
        run(calls_dir, results, Says(SPEECH), FlagsGift())
    assert (results / CALLS_NAME).read_bytes() == before


def test_an_empty_or_broken_labels_file_stops_the_run(calls_dir, tmp_path):
    (calls_dir / "labels.csv").write_text("file,label,scam_type,money_ask_s\n", encoding="utf-8")
    with pytest.raises(EvalStopped):
        run(calls_dir, tmp_path / "results", Says(SPEECH), FlagsGift())

    (calls_dir / "labels.csv").write_text("file,label,scam_type,money_ask_s\ngone.wav,1,,\n", encoding="utf-8")
    with pytest.raises(EvalStopped):
        run(calls_dir, tmp_path / "results", Says(SPEECH), FlagsGift())
    assert not (tmp_path / "results").exists()


def test_a_labels_file_saved_by_excel_with_a_byte_order_mark_still_lists_its_calls(calls_dir, tmp_path):
    (calls_dir / "labels.csv").write_bytes(b"\xef\xbb\xbf" + LABELS.encode("utf-8"))

    payload = run(calls_dir, tmp_path / "results", Says(SPEECH), FlagsGift(), dry_run=True)

    assert [row["file"] for row in payload["calls"]] == ["scam.wav", "ok.wav", "false.wav", "missed.wav"]


def test_totals_with_nothing_to_count_are_none_with_n_zero():
    rows = summarize([], "fake-scorer")

    assert [row["value"] for row in rows] == [None] * len(rows)
    assert [row["n"] for row in rows] == [0] * len(rows)


def test_the_table_merges_every_results_file_in_the_spec_columns(tmp_path):
    row = {"test": "t", "metric": "recall", "value": 0.4, "n": 160, "notes": "a | b"}
    one = {"schema": "second-ear/results-v1", "system": "keyword", "created_utc": "2026-11-14T00:00:00Z", "rows": [row]}
    two = {
        "schema": "second-ear/results-v1",
        "scorer": {"name": "keyword-stand-in", "is_stand_in": True},
        "rows": [{**row, "system": "keyword-stand-in", "value": None}, {**row, "system": "keyword"}],
    }
    (tmp_path / "baselines.json").write_text(json.dumps(one), encoding="utf-8")
    (tmp_path / "heldout.json").write_text(json.dumps(two), encoding="utf-8")
    (tmp_path / "other.json").write_text(json.dumps({"schema": "something-else", "rows": [row]}), encoding="utf-8")

    table = table_markdown(tmp_path)

    assert table.count("| test | metric | value | n | notes |") == 3
    assert table.index("baselines.json") < table.index("heldout.json") and "other.json" not in table
    assert "| t | recall | n/a | 160 | a \\| b |" in table
    assert "Scorer: the keyword stand-in, not a trained model." in table
