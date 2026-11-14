"""Behaviour specs for the Haiku explainer. Strict-xfail until Phase 4 lands.

The fake client has the same surface as `anthropic.Anthropic.messages.create`, so the
specs pin the contract without a network call and without a key.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from server.explainer import GENERIC_SAFE_EXIT, Explainer, Org
from tests.helpers import chunk

pytestmark = pytest.mark.xfail(strict=True, reason="explainer lands in phase 4 — docs/SPEC.md §5")

VALID = json.dumps(
    {
        "scam_type": "gift_card",
        "reason": "Caller wants gift card codes to unlock a refund.",
        "safe_exit_line": "I don't buy gift cards. I'll call you back.",
        "claimed_org": "chase",
    }
)

ORGS = {
    "chase": Org(
        id="chase",
        name="Chase",
        phone="555-0100",
        aliases=("chase",),
        source_url="https://example.test/chase",
        verified_at="2026-11-14",
    ),
    "medicare": Org(id="medicare", name="Medicare", phone=None, aliases=("medicare",)),
}

TRANSCRIPT = [
    chunk("hello, this is Chase fraud department", 4.0),
    chunk("we need you to read the gift card code", 8.0),
]


class FakeAnthropic:
    """Minimal stand-in: records the request, returns fixed text or raises."""

    def __init__(self, text: str = VALID, raises: BaseException | None = None) -> None:
        self.text = text
        self.raises = raises
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(content=[SimpleNamespace(text=self.text)])


def make_explainer(fake: FakeAnthropic) -> Explainer:
    return Explainer(client=fake, orgs=ORGS)


def test_valid_json_becomes_a_result_with_the_org_looked_up():
    result = make_explainer(FakeAnthropic()).explain(TRANSCRIPT, 0.9)
    assert result.degraded is False
    assert result.scam_type == "gift_card"
    assert result.safe_exit_line == "I don't buy gift cards. I'll call you back."
    assert result.claimed_org == "chase"
    assert result.org_name == "Chase"
    assert result.official_number == "555-0100"


def test_bad_json_degrades_to_the_generic_line():
    result = make_explainer(FakeAnthropic(text="not json at all")).explain(TRANSCRIPT, 0.9)
    assert result.degraded is True
    assert result.safe_exit_line == GENERIC_SAFE_EXIT


def test_a_timeout_degrades_instead_of_raising():
    result = make_explainer(FakeAnthropic(raises=TimeoutError("slow"))).explain(TRANSCRIPT, 0.9)
    assert result.degraded is True
    assert result.safe_exit_line == GENERIC_SAFE_EXIT


def test_digit_runs_are_redacted_before_the_request():
    fake = FakeAnthropic()
    transcript = [
        chunk("my card is 4111 1111 1111 1111", 4.0),
        chunk("my social security number is 123 45 6789", 8.0),
    ]
    make_explainer(fake).explain(transcript, 0.9)
    sent = json.dumps(fake.calls[0], default=str)
    assert "4111" not in sent
    assert "6789" not in sent
    assert "[number]" in sent


def test_an_unverified_org_never_renders_a_number():
    text = json.dumps(
        {
            "scam_type": "medicare",
            "reason": "Claims to be Medicare.",
            "safe_exit_line": "I'll call Medicare myself.",
            "claimed_org": "medicare",
        }
    )
    result = make_explainer(FakeAnthropic(text=text)).explain(TRANSCRIPT, 0.9)
    assert result.org_name == "Medicare"
    assert result.official_number is None


def test_a_safe_exit_line_containing_digits_is_rejected():
    text = json.dumps(
        {
            "scam_type": "ssn",
            "reason": "Asks for the number.",
            "safe_exit_line": "Call 1-800-772-1213 and ask for 123456",
            "claimed_org": None,
        }
    )
    result = make_explainer(FakeAnthropic(text=text)).explain(TRANSCRIPT, 0.9)
    assert result.degraded is True
    assert result.safe_exit_line == GENERIC_SAFE_EXIT


def test_an_unknown_scam_type_is_rejected():
    text = json.dumps(
        {
            "scam_type": "phishing",
            "reason": "Some reason.",
            "safe_exit_line": "I'll call you back.",
            "claimed_org": None,
        }
    )
    result = make_explainer(FakeAnthropic(text=text)).explain(TRANSCRIPT, 0.9)
    assert result.degraded is True
