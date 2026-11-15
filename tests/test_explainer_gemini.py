"""The explainer on Gemini: the same rules, another model behind `messages.create`.

Gemini is faked with httpx.MockTransport, so there is no network and no real key. The
digits in the made-up transcripts are invented, and assertions about them are booleans,
so a failure prints none of them.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time

import httpx
import pytest

from server.config import get_settings
from server.explainer import GENERIC_SAFE_EXIT, REQUEST_OPTIONS, Explainer, Org
from server.gemini_client import API_BASE, GEMINI_REQUEST_OPTIONS, KEY_HEADER, GeminiClient
from tests.helpers import chunk

KEY = "secret-gemini-key"
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
}
TRANSCRIPT = [
    chunk("hello, this is Chase fraud department", 4.0),
    chunk("we need you to read the gift card code", 8.0),
]


class Gemini:
    """A fake endpoint: records every request, then answers, refuses, stalls or times out."""

    def __init__(self, text: str = VALID, status: int = 200, times_out: bool = False, delay_s: float = 0.0) -> None:
        self.text = text
        self.status = status
        self.times_out = times_out
        self.delay_s = delay_s
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        time.sleep(self.delay_s)
        if self.times_out:
            raise httpx.ReadTimeout("timed out", request=request)
        if self.status != 200:
            # A real error body can echo things back; none of it may be logged.
            return httpx.Response(self.status, json={"error": {"message": f"refused, key {KEY}"}})
        answer = {"candidates": [{"content": {"parts": [{"text": self.text}]}, "finishReason": "STOP"}]}
        return httpx.Response(200, json=answer)

    def body(self) -> dict:
        return json.loads(self.requests[0].content)


def make_explainer(fake: Gemini, **options: object) -> Explainer:
    client = GeminiClient(KEY, http=httpx.Client(transport=httpx.MockTransport(fake)))
    return Explainer(client=client, orgs=ORGS, provider="gemini", model="gemini-test", **options)


def test_valid_json_from_gemini_becomes_a_result_with_the_org_looked_up():
    fake = Gemini()
    explainer = make_explainer(fake)

    result = explainer.explain(TRANSCRIPT, 0.9)

    assert result.degraded is False and explainer.last_code == "ok"
    assert (result.scam_type, result.claimed_org, result.org_name) == ("gift_card", "chase", "Chase")
    assert result.safe_exit_line == "I don't buy gift cards. I'll call you back."
    assert result.official_number == "555-0100"


def test_the_request_asks_for_json_and_carries_no_anthropic_only_param():
    fake = Gemini()
    explainer = make_explainer(fake)
    explainer.explain(TRANSCRIPT, 0.9)
    sent = fake.body()

    assert str(fake.requests[0].url) == f"{API_BASE}/models/gemini-test:generateContent"
    assert set(sent) == {"systemInstruction", "contents", "generationConfig"}
    assert sent["generationConfig"]["responseMimeType"] == "application/json"
    assert sent["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "MINIMAL"}
    # Gemini counts thinking against an output cap, so the answer-sized cap is not sent.
    assert "maxOutputTokens" not in sent["generationConfig"]
    assert sent["systemInstruction"]["parts"][0]["text"] == explainer._system()
    assert sent["contents"][0]["role"] == "user"
    assert "thinking" not in explainer.request_options
    assert "output_config" not in explainer.request_options


def test_bad_json_from_gemini_degrades_to_the_generic_line():
    explainer = make_explainer(Gemini(text="not json at all"))

    result = explainer.explain(TRANSCRIPT, 0.9)

    assert result.degraded is True and explainer.last_code == "bad_json"
    assert result.safe_exit_line == GENERIC_SAFE_EXIT


def test_an_answer_with_no_candidate_degrades():
    def blocked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"promptFeedback": {"blockReason": "OTHER"}})

    client = GeminiClient(KEY, http=httpx.Client(transport=httpx.MockTransport(blocked)))
    explainer = Explainer(client=client, orgs=ORGS, provider="gemini", model="gemini-test")

    assert explainer.explain(TRANSCRIPT, 0.9).degraded is True
    assert explainer.last_code == "empty_reply"


@pytest.mark.parametrize("status", [503, 429, 500])
def test_a_refused_request_degrades_at_once_with_no_retry(status):
    fake = Gemini(status=status)
    explainer = make_explainer(fake)

    result = explainer.explain(TRANSCRIPT, 0.9)

    assert result.degraded is True and result.safe_exit_line == GENERIC_SAFE_EXIT
    assert explainer.last_code == f"request_failed:http_{status}"
    assert len(fake.requests) == 1


def test_a_gemini_timeout_degrades_with_no_retry():
    fake = Gemini(times_out=True)
    explainer = make_explainer(fake)

    result = explainer.explain(TRANSCRIPT, 0.9)

    assert result.degraded is True and result.safe_exit_line == GENERIC_SAFE_EXIT
    assert explainer.last_code == "request_failed:ReadTimeout"
    assert len(fake.requests) == 1


def test_a_slow_gemini_degrades_inside_the_budget():
    explainer = make_explainer(Gemini(delay_s=0.5), timeout_s=0.05)

    started = time.monotonic()
    result = explainer.explain(TRANSCRIPT, 0.9)
    elapsed = time.monotonic() - started

    assert result.degraded is True and explainer.last_code == "timeout"
    assert elapsed < 0.4


def test_no_number_from_the_call_reaches_gemini():
    fake = Gemini()
    transcript = [
        chunk("my card is 4111 1111 1111 1111", 4.0),
        chunk("my social is 123 45 6789 and the code is 739", 8.0),
        chunk("my pin is four eight one five", 12.0),
    ]
    make_explainer(fake).explain(transcript, 0.9)
    raw = fake.requests[0].content.decode("utf-8")
    said = fake.body()["contents"][0]["parts"][0]["text"]

    # The fixed instructions hold their own limits (120, 160 characters) and the token
    # cap is a number. Nothing that was said on the call may be among them.
    leaked = any(piece in raw for piece in ("4111", "6789", "739", "four eight"))
    assert leaked is False
    assert any(character.isdigit() for character in said) is False
    assert "[number]" in said


def test_the_key_travels_in_a_header_and_never_in_the_url_or_the_logs(caplog):
    caplog.set_level(logging.DEBUG)
    fakes = [Gemini(), Gemini(status=503), Gemini(times_out=True), Gemini(text="zebra is not json")]
    for fake in fakes:
        make_explainer(fake).explain([chunk("walrus pineapple 4111 1111 1111 1111", 4.0)], 0.9)

    requests = [request for fake in fakes for request in fake.requests]
    assert len(requests) == 4
    assert all(request.headers[KEY_HEADER] == KEY for request in requests)
    assert not any(KEY in str(request.url) for request in requests)
    leaked = any(word in caplog.text for word in (KEY, "walrus", "pineapple", "zebra", "4111"))
    assert leaked is False
    assert "explainer degraded: request_failed:http_503" in caplog.text


def test_the_provider_setting_picks_the_client_the_model_and_the_options(monkeypatch):
    base = get_settings()
    on_gemini = dataclasses.replace(base, explainer_provider="gemini", gemini_api_key=KEY, gemini_model="gemini-x")
    monkeypatch.setattr("server.explainer.get_settings", lambda: on_gemini)
    gemini = Explainer(orgs=ORGS)

    assert (gemini.provider, gemini.model) == ("gemini", "gemini-x")
    assert gemini.request_options == dict(GEMINI_REQUEST_OPTIONS)
    assert isinstance(gemini._resolve_client(), GeminiClient)

    on_anthropic = dataclasses.replace(base, explainer_provider="anthropic", anthropic_api_key=None)
    monkeypatch.setattr("server.explainer.get_settings", lambda: on_anthropic)
    default = Explainer(orgs=ORGS)

    assert (default.provider, default.model) == ("anthropic", base.haiku_model)
    assert default.request_options == dict(REQUEST_OPTIONS)


def test_gemini_without_a_key_makes_no_request(monkeypatch):
    keyless = dataclasses.replace(get_settings(), explainer_provider="gemini", gemini_api_key=None)
    monkeypatch.setattr("server.explainer.get_settings", lambda: keyless)
    explainer = Explainer(orgs=ORGS)

    result = explainer.explain(TRANSCRIPT, 0.9)

    assert result.degraded is True and explainer.last_code == "no_api_key"


def test_no_test_can_reach_a_real_model_whatever_env_holds():
    settings = get_settings()

    assert settings.anthropic_api_key is None and settings.gemini_api_key is None
    assert settings.explainer_provider == "anthropic"
