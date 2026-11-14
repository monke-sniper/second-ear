"""Green invariants of the scaffold: contracts, constants, data honesty.

These pass today and must keep passing. They pin the things that would silently
drift while the modules get filled in — the frame size, the frozen thresholds, the
"no unverified phone numbers" rule, and the wire models' strictness.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server import alerts, danger, explainer, scorer
from server.contracts import FRAME_BYTES, AlertLevel, ExplainerResult, RiskEvent


def test_frame_contract_is_250ms_of_16k_mono_s16():
    assert FRAME_BYTES == 8_000


def test_frozen_thresholds():
    assert alerts.CAUTION_THRESHOLD == 0.50
    assert alerts.SCAM_THRESHOLD == 0.85
    assert alerts.SCAM_CONSECUTIVE == 2
    assert danger.DIGIT_MIN == 6
    assert danger.WINDOW_S == 10.0
    assert explainer.TIMEOUT_S == 4.0


def test_wire_models_forbid_unknown_fields():
    with pytest.raises(ValidationError):
        RiskEvent(score=0.4, t_s=1.0, surprise="nope")


def test_alert_levels_are_the_documented_three():
    assert [level.value for level in AlertLevel] == ["none", "caution", "scam"]


def test_load_scorer_falls_back_to_stub_without_a_model(tmp_path):
    assert isinstance(scorer.load_scorer(tmp_path / "missing"), scorer.StubScorer)


def test_every_org_phone_is_verified_or_absent():
    orgs = explainer.load_orgs()
    assert len(orgs) >= 12
    for org in orgs.values():
        if org.phone:
            assert org.verified_at, f"{org.id} has a phone but no verified_at"
            assert org.source_url, f"{org.id} has a phone but no source_url"


def test_explainer_result_defaults_are_safe():
    result = ExplainerResult(scam_type="other", reason="r", safe_exit_line="s")
    assert result.official_number is None
    assert result.degraded is False
