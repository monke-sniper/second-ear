"""Behaviour specs for the code warning. Green since Phase 4.

New assertions compare counts and booleans, so a failure never prints a digit run.
"""

from __future__ import annotations

import pytest

from server.danger import (
    DIGIT_MIN,
    WINDOW_S,
    count_digits,
    normalize_spoken_numbers,
    scan,
)
from server.numbers import find_number_runs
from tests.helpers import chunk


def test_spoken_digits_are_normalised_for_counting():
    out = normalize_spoken_numbers("my card is four five six seven eight nine")
    assert "456789" in out


def test_oh_and_double_are_understood():
    out = normalize_spoken_numbers("it starts oh four, then double seven")
    assert "0" in out
    assert "77" in out


def test_six_digits_at_high_risk_fire():
    decision = scan(
        [chunk("four five six seven eight nine", 4.0)], risk=0.90, scam_active=False, now_s=4.0
    )
    assert decision.fired is True
    assert decision.digit_count >= DIGIT_MIN


def test_six_digits_at_low_risk_do_not_fire():
    decision = scan(
        [chunk("four five six seven eight nine", 4.0)], risk=0.20, scam_active=False, now_s=4.0
    )
    assert decision.fired is False


def test_an_active_scam_alert_arms_the_digit_check():
    decision = scan(
        [chunk("four five six seven eight nine", 4.0)], risk=0.10, scam_active=True, now_s=4.0
    )
    assert decision.fired is True


def test_a_pharmacy_reading_a_phone_number_at_low_risk_does_not_fire():
    text = "the pharmacy number is nine zero five, six zero eight, one one six eight"
    decision = scan([chunk(text, 4.0)], risk=0.20, scam_active=False, now_s=4.0)
    assert decision.fired is False


def test_digits_outside_the_window_do_not_count():
    decision = scan(
        [chunk("four five six seven eight nine", 4.0)],
        risk=0.90,
        scam_active=False,
        now_s=4.0 + WINDOW_S + 1.0,
    )
    assert decision.fired is False


def test_the_decision_never_carries_the_digits():
    decision = scan(
        [chunk("four five six seven eight nine", 4.0)], risk=0.90, scam_active=False, now_s=4.0
    )
    assert set(decision.model_dump().keys()) == {"fired", "digit_count", "window_s", "at_s"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("oh, really", 0, id="oh-alone"),
        pytest.param("oh oh, I forgot", 0, id="oh-twice"),
        pytest.param("this one", 0, id="lone-one"),
        pytest.param("it costs 5 dollars", 0, id="lone-numeral"),
        pytest.param("five hundred dollars", 0, id="amount-in-words"),
        pytest.param("double check that one", 0, id="double-as-a-verb"),
        pytest.param("Oh, four of them came", 0, id="oh-as-a-sigh-before-a-number"),
        pytest.param("I counted four. Oh, I forgot.", 0, id="oh-as-a-sigh-after-a-number"),
        pytest.param("Four. Oh. Seven.", 3, id="oh-between-two-numbers"),
        pytest.param("four, uh, five, um, six", 3, id="fillers-inside-a-read-out"),
        pytest.param("it starts oh four, then double seven", 4, id="oh-next-to-a-number"),
        pytest.param("triple four", 3, id="triple"),
        pytest.param("sixteen", 2, id="teen"),
        pytest.param("forty-one eleven", 4, id="tens-and-teens"),
        pytest.param("Four. Five. Six. Seven. Eight. Nine.", 6, id="one-word-sentences"),
        pytest.param("4, 5, 6, 7, 8, 9", 6, id="numerals-with-commas"),
        pytest.param("123-45-6789", 9, id="numerals-with-hyphens"),
        pytest.param("4111 1111 1111 1111", 16, id="numerals-in-groups"),
    ],
)
def test_only_number_runs_of_two_or_more_digits_count(text, expected):
    assert count_digits(text) == expected


def test_oh_and_a_lone_one_are_left_as_words():
    text = "oh, really, this one"
    assert normalize_spoken_numbers(text) == text


def test_a_number_split_across_two_chunks_still_counts():
    chunks = [chunk("my card is four", 4.0), chunk("five six seven eight nine", 8.0)]
    decision = scan(chunks, risk=0.90, scam_active=False, now_s=8.0)
    assert decision.digit_count == 6
    assert decision.fired is True


def test_five_digits_do_not_fire():
    decision = scan(
        [chunk("four five six seven eight", 4.0)], risk=0.90, scam_active=False, now_s=4.0
    )
    assert decision.fired is False


def test_risk_exactly_at_the_gate_does_not_arm():
    decision = scan(
        [chunk("four five six seven eight nine", 4.0)], risk=0.50, scam_active=False, now_s=4.0
    )
    assert decision.fired is False


def test_a_printed_number_run_never_shows_its_digits():
    runs = find_number_runs("four five six seven eight nine")
    leaked = any("456789" in repr(run) for run in runs)
    assert len(runs) == 1
    assert leaked is False
