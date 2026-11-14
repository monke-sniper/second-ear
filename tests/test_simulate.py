"""POST /simulate: text chunks through the same pipeline as the socket, over HTTP."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import create_app
from server.config import get_settings
from server.explainer import GENERIC_SAFE_EXIT, Explainer
from server.scorer import KeywordStandInScorer
from tests.conftest import Harness, scripted
from tests.helpers import FAKE_ORGS, FakeAnthropic, FakeTranscriber

GRANDPARENT_CALL = [
    "Hi grandma, it's me, your grandson.",
    "I'm in trouble. I was in an accident and I'm in jail right now.",
    "Please don't tell mom. I need you to help me with bail today.",
    "My lawyer says you have to buy gift cards right away.",
    "Read me the code on the back of the gift card.",
    "four seven two nine one one three eight five zero six two",
]
PHARMACY_CALL = [
    "Hello, this is the pharmacy on Main Street.",
    "Your prescription is ready to pick up before six this evening.",
    "You can reach us on five five five, zero one four two.",
    "Have a nice day.",
]


def test_simulate_answers_with_the_contracted_shape():
    harness = scripted([], [0.6, 0.9, 0.9])
    with harness.client() as client:
        response = client.post("/simulate", json={"chunks": ["a", "b", "c"], "chunk_seconds": 3.0})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"timeline", "alerts", "explainers", "danger"}
    assert body["timeline"] == [
        {"t_s": 3.0, "score": 0.6, "level": "caution"},
        {"t_s": 6.0, "score": 0.9, "level": "caution"},
        {"t_s": 9.0, "score": 0.9, "level": "scam"},
    ]
    assert [(a["level"], a["t_s"], a["trigger"]) for a in body["alerts"]] == [
        ("caution", 3.0, "smoothed_risk"),
        ("scam", 9.0, "two_high_chunks"),
    ]
    assert [e["type"] for e in body["explainers"]] == ["explainer", "explainer"]


def test_simulate_never_sends_a_push():
    harness = scripted([], [0.9])
    with harness.client() as client:
        body = client.post("/simulate", json={"chunks": GRANDPARENT_CALL}).json()

    assert [a["level"] for a in body["alerts"]] == ["caution", "scam"]
    assert len(body["danger"]) == 1
    assert harness.http.posts == []


def test_a_grandparent_scam_alerts_on_the_stand_in_scorer():
    harness = Harness(scorer=KeywordStandInScorer())
    with harness.client() as client:
        body = client.post("/simulate", json={"chunks": GRANDPARENT_CALL}).json()

    assert [a["level"] for a in body["alerts"]] == ["caution", "scam"]
    assert [d["digit_count"] for d in body["danger"]] == [12]
    assert len(body["explainers"]) == 2


def test_an_ordinary_call_raises_nothing_on_the_stand_in_scorer():
    harness = Harness(scorer=KeywordStandInScorer())
    with harness.client() as client:
        body = client.post("/simulate", json={"chunks": PHARMACY_CALL}).json()

    assert body["alerts"] == [] and body["explainers"] == [] and body["danger"] == []
    assert {point["level"] for point in body["timeline"]} == {"none"}
    assert harness.anthropic.calls == []


def test_without_an_anthropic_key_the_alerts_stand_and_the_line_is_generic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    try:
        app = create_app(
            transcriber=FakeTranscriber(),
            scorer=KeywordStandInScorer(),
            explainer=Explainer(orgs=FAKE_ORGS),  # no client and no key
            notifier_factory=Harness().notifier,
        )
        with TestClient(app) as client:
            body = client.post("/simulate", json={"chunks": GRANDPARENT_CALL}).json()
    finally:
        get_settings.cache_clear()

    assert [a["level"] for a in body["alerts"]] == ["caution", "scam"]
    assert [e["degraded"] for e in body["explainers"]] == [True, True]
    assert {e["safe_exit_line"] for e in body["explainers"]} == {GENERIC_SAFE_EXIT}


def test_simulate_rejects_an_empty_call(client):
    assert client.post("/simulate", json={"chunks": []}).status_code == 422


def test_the_response_never_holds_the_digits_that_were_read():
    harness = scripted([], [0.9], anthropic=FakeAnthropic())
    chunks = ["hello", "my card is 4111 1111 1111 1111"]
    with harness.client() as client:
        text = client.post("/simulate", json={"chunks": chunks}).text

    leaked = "4111" in text
    assert leaked is False
