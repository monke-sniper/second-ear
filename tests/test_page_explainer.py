"""The page's half of the explainer: Firebase settings, what the page is told, what it may say.

The model call itself runs in the browser, through Firebase AI Logic. Nothing here reaches
Firebase or a model: these pin the settings, the config the page fetches, the shape of the
page's answer, and that the answer goes through the same checks as Haiku's.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Iterator

import pytest

from server.config import DEFAULT_FIREBASE_MODEL, ROOT, FirebaseSettings, get_settings
from server.contracts import MAX_REPLY_CHARS
from server.explainer import GENERIC_SAFE_EXIT, SCAM_TYPES, Explainer
from server.explainer_checks import NO_ORG
from server.page_explainer import PageDesk, parse_explained, reply_schema
from tests.conftest import Harness
from tests.helpers import EXPLAINER_REPLY, FAKE_ORGS, FakeAnthropic, chunk

FIREBASE = FirebaseSettings(api_key="test-api-key", project_id="second-ear-test", app_id="1:2:web:3")
CARD = "four one one one two two two two three three three three"


def reply(**changes: object) -> str:
    """The stock answer with some fields changed, as the JSON text a model returns."""
    return json.dumps({**json.loads(EXPLAINER_REPLY), **changes})


@pytest.fixture()
def fresh_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Let a test set the environment, and have the real one re-read afterwards."""
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


# ------------------------------------------------------------------------ settings


def test_firebase_is_on_only_when_all_three_values_are_set(fresh_settings):
    fresh_settings.setenv("FIREBASE_API_KEY", "key")
    fresh_settings.setenv("FIREBASE_PROJECT_ID", "project")
    fresh_settings.setenv("FIREBASE_APP_ID", "app")
    fresh_settings.delenv("FIREBASE_AI_MODEL", raising=False)

    firebase = get_settings().firebase

    assert firebase == FirebaseSettings(api_key="key", project_id="project", app_id="app")
    assert firebase.model == DEFAULT_FIREBASE_MODEL


@pytest.mark.parametrize("missing", ["FIREBASE_API_KEY", "FIREBASE_PROJECT_ID", "FIREBASE_APP_ID"])
def test_one_missing_firebase_value_leaves_the_page_explainer_off(fresh_settings, missing):
    for name in ("FIREBASE_API_KEY", "FIREBASE_PROJECT_ID", "FIREBASE_APP_ID"):
        fresh_settings.setenv(name, "" if name == missing else "set")

    assert get_settings().firebase is None


def test_the_cloud_model_can_be_changed_from_the_environment(fresh_settings):
    for name in ("FIREBASE_API_KEY", "FIREBASE_PROJECT_ID", "FIREBASE_APP_ID"):
        fresh_settings.setenv(name, "set")
    fresh_settings.setenv("FIREBASE_AI_MODEL", "gemini-test")

    assert get_settings().firebase.model == "gemini-test"


def test_env_example_documents_the_firebase_settings_and_holds_no_value():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()

    for name in ("FIREBASE_API_KEY", "FIREBASE_PROJECT_ID", "FIREBASE_APP_ID"):
        assert f"{name}=" in lines
    assert f"FIREBASE_AI_MODEL={DEFAULT_FIREBASE_MODEL}" in lines


# ------------------------------------------------------- what the page is told


def test_without_firebase_the_page_is_told_the_explainer_is_not_its_job(client):
    response = client.get("/explainer/config")

    assert response.status_code == 200
    assert response.json() == {"enabled": False}


def test_with_firebase_the_page_gets_what_it_needs_to_make_the_call():
    harness = Harness(firebase=FIREBASE)
    with harness.client() as client:
        response = client.get("/explainer/config")

    config = response.json()
    assert response.headers["cache-control"] == "no-store"
    assert config["enabled"] is True
    assert config["firebase"] == {
        "apiKey": "test-api-key",
        "projectId": "second-ear-test",
        "appId": "1:2:web:3",
    }
    assert config["model"] == DEFAULT_FIREBASE_MODEL
    assert config["system"] == harness.explainer().page_system()
    assert config["reply_schema"] == reply_schema(SCAM_TYPES, FAKE_ORGS.keys())
    # Nothing the page does not use: the 4 s budget is the server's to keep.
    assert set(config) == {"enabled", "firebase", "model", "system", "reply_schema"}


def test_the_pages_instructions_name_the_word_its_schema_uses_for_no_organisation():
    explainer = Explainer(client=FakeAnthropic(), orgs=FAKE_ORGS)

    assert f'or "{NO_ORG}" if they claim none of them' in explainer.page_system()
    assert "or null if they claim none of them" in explainer._system()  # Haiku's are unchanged


def test_the_reply_schema_allows_only_the_fixed_scam_types_and_the_listed_organisations():
    schema = reply_schema(SCAM_TYPES, ["chase", "medicare"])

    assert schema["type"] == "object"
    assert schema["properties"]["scam_type"] == {"type": "string", "enum": list(SCAM_TYPES)}
    # A schema cannot say null on every model, so "no organisation" is a word of its own.
    assert schema["properties"]["claimed_org"] == {"type": "string", "enum": ["chase", "medicare", NO_ORG]}
    assert schema["required"] == ["scam_type", "reason", "safe_exit_line", "claimed_org"]


# --------------------------------------------------------- what the page may say


def test_a_well_formed_answer_is_read():
    answer = parse_explained(json.dumps({"type": "explained", "id": 3, "text": "{}", "source": "on_device"}))

    assert (answer.id, answer.text, answer.source) == (3, "{}", "on_device")


@pytest.mark.parametrize(
    "message",
    [
        "not json",
        "[1, 2]",
        {"type": "explained", "id": 1, "text": "{}"},  # no source
        {"type": "explained", "id": 1, "text": "{}", "source": "somewhere"},
        {"type": "explained", "id": "1", "text": "{}", "source": "in_cloud"},
        {"type": "explained", "id": True, "text": "{}", "source": "in_cloud"},
        {"type": "explained", "id": -1, "text": "{}", "source": "in_cloud"},
        {"type": "explained", "id": 1, "text": 5, "source": "in_cloud"},
        {"type": "explained", "id": 1, "text": "x" * (MAX_REPLY_CHARS + 1), "source": "in_cloud"},
        {"type": "explained", "id": 1, "text": "{}", "source": "in_cloud", "extra": 1},
    ],
)
def test_a_malformed_answer_is_not_read(message):
    text = message if isinstance(message, str) else json.dumps(message)

    assert parse_explained(text) is None


def test_a_desk_hands_each_answer_to_the_request_that_is_waiting_for_it():
    async def scenario() -> tuple[str, bool, bool]:
        desk = PageDesk()
        first_id, first = desk.expect()
        second_id, _second = desk.expect()
        answer = parse_explained(
            json.dumps({"type": "explained", "id": first_id, "text": "{}", "source": "in_cloud"})
        )
        taken = desk.settle(answer)
        desk.close(first_id)
        late = desk.settle(answer)  # nobody is waiting for it any more
        assert second_id != first_id
        return (await first).text, taken, late

    assert asyncio.run(scenario()) == ("{}", True, False)


# ------------------------------------------ the page's answer, checked like Haiku's


def test_the_pages_answer_goes_through_the_same_checks_and_the_org_lookup():
    anthropic = FakeAnthropic()
    explainer = Explainer(client=anthropic, orgs=FAKE_ORGS)

    result = explainer.from_reply(reply(claimed_org="chase"))

    assert result.degraded is False
    assert (result.scam_type, result.claimed_org, result.org_name) == ("grandparent", "chase", "Chase")
    assert result.official_number is None  # the fixture's phone is not verified
    assert explainer.last_code == "ok"
    assert anthropic.calls == []  # checking an answer asks no model


def test_the_schemas_word_for_no_organisation_means_none():
    explainer = Explainer(client=FakeAnthropic(), orgs=FAKE_ORGS)

    result = explainer.from_reply(reply(claimed_org=NO_ORG))

    assert result.degraded is False and result.claimed_org is None and result.org_name is None


def test_only_the_pages_answer_may_use_that_word():
    # Haiku is told to say null; "none" from Haiku is an unknown organisation.
    explainer = Explainer(client=FakeAnthropic(text=reply(claimed_org=NO_ORG)), orgs=FAKE_ORGS)

    result = explainer.explain([chunk("hi grandma it is me", 4.0)], 0.9)

    assert result.degraded is True and explainer.last_code == "invalid:claimed_org"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("", "empty_reply"),
        ("   ", "empty_reply"),
        ("the caller is a scammer", "bad_json"),
        (reply(scam_type="lottery"), "invalid:scam_type"),
        (reply(safe_exit_line="Call me back on 555 0100."), "invalid:safe_exit_line"),
        (reply(safe_exit_line=f"My card is {CARD}."), "invalid:safe_exit_line"),
        (reply(reason="x" * 121), "invalid:reason"),
        (reply(claimed_org="acme"), "invalid:claimed_org"),
    ],
)
def test_a_bad_answer_from_the_page_degrades_to_the_generic_line(text, code, caplog):
    explainer = Explainer(client=FakeAnthropic(), orgs=FAKE_ORGS)

    with caplog.at_level(logging.WARNING):
        result = explainer.from_reply(text)

    assert result.degraded is True and result.safe_exit_line == GENERIC_SAFE_EXIT
    assert explainer.last_code == code
    # The code is logged, never the answer.
    assert f"explainer degraded: {code}" in caplog.text
    leaked = "555" in caplog.text or "four one one" in caplog.text
    assert leaked is False


def test_a_prompt_for_the_page_holds_no_digit_and_is_none_for_a_silent_call():
    explainer = Explainer(client=FakeAnthropic(), orgs=FAKE_ORGS)

    prompt = explainer.prompt_text([chunk(f"read me the card {CARD} and 4111", 4.0)])

    assert "<transcript>" in prompt and "[number]" in prompt
    leaked = any(char.isdigit() for char in prompt) or "four one one" in prompt
    assert leaked is False
    assert explainer.prompt_text([]) is None
    assert explainer.prompt_text([chunk("   ", 4.0)]) is None


def test_a_degraded_result_takes_a_fixed_code_and_keeps_the_alert_safe(caplog):
    explainer = Explainer(client=FakeAnthropic(), orgs=FAKE_ORGS)

    with caplog.at_level(logging.WARNING):
        result = explainer.degraded("page_timeout")

    assert result.degraded is True and result.safe_exit_line == GENERIC_SAFE_EXIT
    assert explainer.last_code == "page_timeout"
    assert "explainer degraded: page_timeout" in caplog.text
