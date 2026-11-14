"""Behaviour specs for the alert rules. Green since Phase 4.

Each test is one sentence of docs/SPEC.md §2 or §4. If a rule changes, change the
spec and its test in the same commit.
"""

from __future__ import annotations

import pytest

from server.alerts import decide, smoothed
from server.contracts import AlertLevel, ScorePoint


def points(*scores: float) -> list[ScorePoint]:
    return [ScorePoint(t_s=float(i * 4), score=s) for i, s in enumerate(scores)]


def test_empty_history_is_none():
    assert decide([]).level is AlertLevel.none


def test_one_high_chunk_is_not_a_scam_alert():
    assert decide(points(0.90)).level is AlertLevel.caution


def test_two_high_chunks_in_a_row_are_a_scam_alert():
    decision = decide(points(0.90, 0.90))
    assert decision.level is AlertLevel.scam
    assert decision.t_s == 4.0
    assert decision.trigger == "two_high_chunks"


def test_third_high_chunk_does_not_move_the_alert_time():
    decision = decide(points(0.90, 0.90, 0.95))
    assert decision.level is AlertLevel.scam
    assert decision.t_s == 4.0


def test_scam_is_sticky_after_the_scores_drop():
    assert decide(points(0.90, 0.90, 0.10, 0.05)).level is AlertLevel.scam


def test_caution_at_half():
    decision = decide(points(0.55))
    assert decision.level is AlertLevel.caution


def test_quiet_call_stays_none():
    assert decide(points(0.10, 0.20, 0.30)).level is AlertLevel.none


def test_smoothing_is_the_trailing_mean_of_three():
    assert smoothed([0.0, 0.0, 0.9])[-1] == pytest.approx(0.3)
    assert smoothed([0.9]) == [pytest.approx(0.9)]


def test_exactly_the_scam_threshold_twice_is_not_a_scam_alert():
    assert decide(points(0.85, 0.85)).level is AlertLevel.caution


def test_high_chunks_must_be_consecutive():
    assert decide(points(0.90, 0.10, 0.90)).level is AlertLevel.caution


def test_caution_is_inclusive_at_exactly_half():
    decision = decide(points(0.50))
    assert decision.level is AlertLevel.caution
    assert decision.t_s == 0.0
    assert decision.trigger == "smoothed_risk"


def test_caution_clears_when_the_smoothed_risk_falls():
    decision = decide(points(0.60, 0.10, 0.10))
    assert decision.level is AlertLevel.none
    assert decision.t_s is None
    assert decision.trigger is None


def test_caution_time_is_the_start_of_the_current_stretch():
    decision = decide(points(0.60, 0.10, 0.10, 0.80, 0.80))
    assert decision.level is AlertLevel.caution
    assert decision.t_s == 16.0


def test_the_alert_score_is_the_value_that_crossed_the_threshold():
    assert decide(points(0.40, 0.80)).score == pytest.approx(0.60)
    assert decide(points(0.20, 0.90, 0.95)).score == pytest.approx(0.95)
    assert decide(points(0.20, 0.90, 0.95, 0.10)).score == pytest.approx(0.95)
