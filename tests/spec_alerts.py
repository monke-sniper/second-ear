"""Behaviour specs for the alert rules. Strict-xfail until Phase 4 lands.

Each test is one sentence of docs/SPEC.md §2. When you implement `alerts.decide`,
delete the module-level xfail marker; a strict xfail turns into a failure the moment
the test passes, so the suite tells you when the marker is stale.
"""

from __future__ import annotations

import pytest

from server.alerts import decide, smoothed
from server.contracts import AlertLevel, ScorePoint

pytestmark = pytest.mark.xfail(strict=True, reason="alerts land in phase 4 — docs/SPEC.md §4")


def points(*scores: float) -> list[ScorePoint]:
    return [ScorePoint(t_s=float(i * 4), score=s) for i, s in enumerate(scores)]


def test_empty_history_is_none():
    assert decide([]).level is AlertLevel.none


def test_one_high_chunk_is_not_a_scam_alert():
    assert decide(points(0.90)).level is AlertLevel.none


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
