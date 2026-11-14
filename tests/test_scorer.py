"""The scorers: the keyword stand-in, the loaders, and the DistilBERT wrapper.

The DistilBERT test builds a tiny random model in a temp folder. It proves the
wrapper loads, truncates from the left and returns 0..1 — not that the model is good.
"""

from __future__ import annotations

import re

import pytest

from server import scorer
from server.greeting import GREETING_PATTERN, strip_greeting
from server.scorer import DistilBertRiskScorer, KeywordStandInScorer, RedFlag

GRANDPARENT_CALL = (
    "Hi grandma, it's me, your grandson. I'm in trouble. I was in an accident and "
    "I'm in jail. Please don't tell mom. I need bail money. My lawyer says you have "
    "to buy gift cards right away."
)
PHARMACY_CALL = (
    "Hello, this is the pharmacy on Main Street. Your prescription is ready to pick up "
    "any time before six this evening. Have a nice day."
)


def test_stand_in_scores_empty_text_as_zero():
    assert KeywordStandInScorer().score("") == 0.0
    assert KeywordStandInScorer().score("   \n") == 0.0


def test_stand_in_leaves_an_ordinary_call_at_zero():
    assert KeywordStandInScorer().score(PHARMACY_CALL) == 0.0


def test_stand_in_puts_a_grandparent_scam_above_the_scam_threshold():
    assert KeywordStandInScorer().score(GRANDPARENT_CALL) > 0.85


def test_stand_in_climbs_as_more_flags_are_heard_and_never_passes_one():
    stand_in = KeywordStandInScorer()
    words = GRANDPARENT_CALL.split()
    scores = [stand_in.score(" ".join(words[:end])) for end in range(1, len(words) + 1)]

    assert scores == sorted(scores)
    assert all(0.0 <= value <= 1.0 for value in scores)


def test_stand_in_counts_a_flag_once_however_often_it_is_said():
    stand_in = KeywordStandInScorer((RedFlag(0.4, ("gift card", "gift cards")),))

    assert stand_in.score("gift card gift cards, a gift card") == pytest.approx(0.4)


def test_stand_in_matches_whole_words_and_curly_apostrophes():
    stand_in = KeywordStandInScorer((RedFlag(0.4, ("bail", "don't tell")),))

    assert stand_in.score("my friend bailey called") == 0.0
    assert stand_in.score("Don’t tell anyone.") == pytest.approx(0.4)


def test_stand_in_only_hears_the_last_two_hundred_words():
    filler = " ".join(["weather"] * scorer.STAND_IN_WINDOW_WORDS)

    assert KeywordStandInScorer().score(f"{GRANDPARENT_CALL} {filler}") == 0.0


def test_app_scorer_is_the_stand_in_until_a_model_folder_exists(tmp_path):
    assert isinstance(scorer.load_app_scorer(tmp_path / "missing"), KeywordStandInScorer)


def test_app_scorer_is_distilbert_once_the_folder_has_a_config(tmp_path):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")

    loaded = scorer.load_app_scorer(tmp_path)

    assert isinstance(loaded, DistilBertRiskScorer)
    assert loaded.is_loaded is False  # nothing is read until the first score


@pytest.fixture(scope="module")
def tiny_model_dir(tmp_path_factory):
    """A random two-label DistilBERT with a ten-word vocabulary. Nothing is downloaded."""
    from transformers import DistilBertConfig, DistilBertForSequenceClassification
    from transformers import DistilBertTokenizer

    folder = tmp_path_factory.mktemp("tiny-risk-scorer")
    vocab = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", "gift", "card", "hello", "bail", "now"]
    vocab_file = folder / "vocab.txt"
    vocab_file.write_text("\n".join(vocab) + "\n", encoding="utf-8")
    DistilBertTokenizer(str(vocab_file)).save_pretrained(folder)
    config = DistilBertConfig(
        vocab_size=len(vocab), dim=16, hidden_dim=32, n_layers=1, n_heads=2, num_labels=2
    )
    DistilBertForSequenceClassification(config).save_pretrained(folder)
    return folder


def test_distilbert_scores_between_zero_and_one(tiny_model_dir):
    model = DistilBertRiskScorer(tiny_model_dir)

    value = model.score("hello gift card now")

    assert 0.0 <= value <= 1.0
    assert model.is_loaded is True


def test_distilbert_scores_empty_text_as_zero_without_loading(tiny_model_dir):
    model = DistilBertRiskScorer(tiny_model_dir)

    assert model.score("  ") == 0.0
    assert model.is_loaded is False


def test_distilbert_keeps_the_end_of_a_long_transcript(tiny_model_dir):
    model = DistilBertRiskScorer(tiny_model_dir)
    long_start = " ".join(["hello"] * 600)

    with_tail = model.score(f"{long_start} gift card bail now")
    tail_only = model.score(" ".join(["hello"] * 250) + " gift card bail now")

    # Left truncation: both inputs end in the same 254 tokens, so they score the same.
    assert with_tail == pytest.approx(tail_only, abs=1e-6)
    assert model._tokenizer.truncation_side == "left"


# ------------------------------------------------- the training greeting rule


def test_the_greeting_rule_is_the_one_training_used_character_for_character():
    # Copied from ml/README.md. If training changes its rule, this must change with it.
    assert GREETING_PATTERN.pattern == (
        r"^\s*(?:hello|hi|hey|good\s+(?:morning|afternoon|evening))\b[\s,.!?;:\-\u2013\u2014]*"
    )
    assert GREETING_PATTERN.flags & re.IGNORECASE


def test_strip_greeting_removes_one_leading_greeting_and_its_punctuation():
    assert strip_greeting("Hello? This is your pharmacy") == "This is your pharmacy"
    assert strip_greeting("Good  morning \u2014 it's me") == "it's me"
    assert strip_greeting("Hello, hello") == "hello"
    assert strip_greeting("History is long. Hello there") == "History is long. Hello there"


def handed_to_tokenizer(model: DistilBertRiskScorer, transcript: str) -> list[str]:
    """Score `transcript` and return the text the tokenizer was given.

    The tiny model is random, so two different inputs can score within rounding of
    each other. What the tokenizer was handed is the exact thing to assert on.
    """
    model.ensure_loaded()
    real = model._tokenizer
    seen: list[str] = []

    def spy(text, **kwargs):
        seen.append(text)
        return real(text, **kwargs)

    model._tokenizer = spy
    try:
        model.score(transcript)
    finally:
        model._tokenizer = real
    return seen


def test_distilbert_scores_a_call_the_same_with_or_without_its_greeting(tiny_model_dir):
    model = DistilBertRiskScorer(tiny_model_dir)
    bare = model.score("This is your pharmacy")

    assert model.score("Hello? This is your pharmacy") == pytest.approx(bare, abs=1e-6)
    assert handed_to_tokenizer(model, "Hello? This is your pharmacy") == ["This is your pharmacy"]
    # Whitespace is collapsed first, so a greeting behind a line break still goes.
    assert model.score("  Hello?\n\n This   is your pharmacy ") == pytest.approx(bare, abs=1e-6)
    # Only the start of the call is touched; a greeting anywhere else stays.
    later = "This is your pharmacy hello"
    assert handed_to_tokenizer(model, later) == [later]


def test_distilbert_strips_only_the_first_greeting(tiny_model_dir):
    model = DistilBertRiskScorer(tiny_model_dir)

    twice = model.score("Hello, hello")

    # One "hello" is left and scored. Had both gone, nothing would be left: exactly 0.0.
    assert twice > 0.0
    assert twice == pytest.approx(model.score("Hey hello"), abs=1e-6)
    assert handed_to_tokenizer(model, "Hello, hello") == ["hello"]
    assert handed_to_tokenizer(model, "Hello, hello hello") == ["hello hello"]


def test_distilbert_scores_a_bare_greeting_as_zero_without_loading(tiny_model_dir):
    model = DistilBertRiskScorer(tiny_model_dir)

    assert model.score("Hello?") == 0.0
    assert model.is_loaded is False


def test_the_stand_in_does_not_strip_the_greeting():
    stand_in = KeywordStandInScorer((RedFlag(0.4, ("hello",)),))

    assert stand_in.score("Hello? This is your pharmacy") == pytest.approx(0.4)
