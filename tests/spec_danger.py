"""Behaviour specs for the code warning. Strict-xfail until Phase 4 lands."""

from __future__ import annotations

import pytest

from server.danger import DIGIT_MIN, WINDOW_S, normalize_spoken_numbers, scan
from tests.helpers import chunk

pytestmark = pytest.mark.xfail(strict=True, reason="digit rules land in phase 4 — docs/SPEC.md §4")


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
