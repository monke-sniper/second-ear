"""Held-out scoring: the copied metric helpers, the keyword baseline, the scorer record.

Small made-up sets and a fake scorer; no model is loaded and nothing is downloaded.
"""

from __future__ import annotations

import json

from eval import keyword_baseline
from eval.metrics import binary_metrics, file_sha256, metric_rows, prefix_at
from eval.score_heldout import BASELINE, EARLY_TEST, FULL_TEST, build_payload, load_heldout
from eval.scorer_id import STAND_IN_NOTE, describe_scorer
from server.config import ROOT
from server.scorer import KeywordStandInScorer


class FlagsPrize:
    """Scores 0.9 when the text says prize, else 0.1."""

    name = "fake-scorer"

    def score(self, transcript: str) -> float:
        return 0.9 if "prize" in transcript else 0.1


def write_set(path, rows) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def tiny_set(tmp_path):
    rows = [
        {"id": "s1", "label": 1, "type": "prize", "opening": "hello", "text": "Hello you won a prize pay now with a gift card"},
        {"id": "s2", "label": 1, "type": "irs", "opening": "none", "text": "You owe back taxes and must settle the matter today sir"},
        {"id": "l1", "label": 0, "type": "pharmacy", "opening": "hi", "text": "Hi your refill is ready at the pharmacy counter any time"},
        {"id": "l2", "label": 0, "type": "utility", "opening": "this is", "text": "This is the water company the prize draw flyer was ours"},
    ]
    path = tmp_path / "gemini.jsonl"
    write_set(path, rows)
    return path


def test_prefix_is_the_first_forty_percent_of_words_rounded_up():
    assert prefix_at("a b c d e f g h i j", 40) == "a b c d"
    assert prefix_at("a b c d e f g", 40) == "a b c"
    assert prefix_at("alone", 40) == "alone"


def test_a_metric_with_a_zero_denominator_is_none_not_zero():
    metrics = binary_metrics([0, 0], [0, 0])

    assert (metrics["precision"], metrics["recall"], metrics["f1"]) == (None, None, None)
    rows = metric_rows("t", metrics, "context")
    assert [row["value"] for row in rows] == [None, None, None]
    assert [row["n"] for row in rows] == [0, 0, 2]


def test_the_keyword_baseline_is_the_one_baselines_json_was_scored_with():
    recorded = json.loads((ROOT / "eval" / "results" / "baselines.json").read_text(encoding="utf-8"))

    assert list(keyword_baseline.KEYWORDS) == recorded["keywords"]
    assert keyword_baseline.RULE == recorded["rule"]
    assert keyword_baseline.predict("please buy two gift cards") == 1
    assert keyword_baseline.predict("your warranty is expiring") == 0
    assert keyword_baseline.predict("there is a WARRANT out") == 1


def test_heldout_rows_have_the_baselines_shape_for_both_systems(tmp_path):
    path = tiny_set(tmp_path)

    payload = build_payload(load_heldout(path), FlagsPrize(), path)

    assert payload["systems"] == ["fake-scorer", BASELINE]
    assert len(payload["rows"]) == 12
    assert all(set(row) == {"system", "test", "metric", "value", "n", "notes"} for row in payload["rows"])
    assert {row["test"] for row in payload["rows"]} == {FULL_TEST, EARLY_TEST}
    by_key = {(row["system"], row["test"], row["metric"]): row for row in payload["rows"]}
    # The fake scorer flags s1 and l2: tp=1 fp=1 fn=1 tn=1.
    assert by_key[("fake-scorer", FULL_TEST, "precision")]["value"] == 0.5
    assert by_key[("fake-scorer", FULL_TEST, "precision")]["n"] == 2
    assert by_key[("fake-scorer", FULL_TEST, "recall")]["n"] == 2
    assert by_key[("fake-scorer", FULL_TEST, "f1")]["n"] == 4
    # The baseline hits "gift card" in s1 only; in the first 40 % of words it hits nothing.
    assert by_key[(BASELINE, FULL_TEST, "recall")]["value"] == 0.5
    assert by_key[(BASELINE, EARLY_TEST, "precision")]["value"] is None
    assert payload["confusion"]["fake-scorer"][FULL_TEST] == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}
    assert payload["by_opening"][BASELINE][FULL_TEST]["hello"] == {"n": 1, "correct": 1}
    assert payload["heldout"]["sha256"] == file_sha256(path) and payload["heldout"]["rows"] == 4


def test_heldout_results_hold_no_transcript_and_name_their_scorer(tmp_path):
    path = tiny_set(tmp_path)

    payload = build_payload(load_heldout(path), KeywordStandInScorer(), path)
    text = json.dumps(payload)

    assert "refill" not in text and "back taxes" not in text
    assert payload["scorer"]["name"] == "keyword-stand-in"
    assert payload["scorer"]["is_stand_in"] is True
    assert STAND_IN_NOTE in payload["caveats"]


def test_the_scorer_record_ties_a_trained_model_to_model_json(tmp_path):
    class Trained:
        name = "distilbert"
        model_dir = tmp_path / "risk-scorer"

    Trained.model_dir.mkdir()
    (Trained.model_dir / "config.json").write_text("{}", encoding="utf-8")
    weights = Trained.model_dir / "model.safetensors"
    weights.write_bytes(b"weights")
    model_json = tmp_path / "model.json"

    missing = describe_scorer(Trained(), model_json)
    assert missing["is_stand_in"] is False and missing["model_folder_found"] is True
    assert missing["model_json_sha256"] is None and missing["weights_match_model_json"] is None

    model_json.write_text(json.dumps({"export": {"model_safetensors_sha256": file_sha256(weights)}}), encoding="utf-8")
    same = describe_scorer(Trained(), model_json)
    assert same["model_json_sha256"] == file_sha256(model_json)
    assert same["weights_match_model_json"] is True

    weights.write_bytes(b"other weights")
    assert describe_scorer(Trained(), model_json)["weights_match_model_json"] is False


def test_the_scorer_record_for_the_stand_in_fingerprints_its_phrase_list(tmp_path):
    info = describe_scorer(KeywordStandInScorer(), tmp_path / "model.json")

    assert info["weights_sha256"] is None and info["model_json_sha256"] is None
    assert info["stand_in"]["flags"] == len(KeywordStandInScorer().flags)
    assert len(info["stand_in"]["flags_sha256"]) == 64
