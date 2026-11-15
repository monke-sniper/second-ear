"""Behaviour specs for the Haiku explainer. Green since Phase 4.

The fake client has the same surface as `anthropic.Anthropic.messages.create`, so the
specs pin the contract without a network call and without a key. The real request
is checked by scripts/smoke_explainer.py, not here.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import time
from types import SimpleNamespace

import pytest

from server.config import get_settings
from server.explainer import GENERIC_SAFE_EXIT, Explainer, Org
from server.explainer_prompt import redact_for_prompt, redact_outbound
from server.numbers import find_number_runs
from server.orgs import load_orgs
from tests.helpers import chunk

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


class SlowAnthropic(FakeAnthropic):
    """Answers correctly, but only after the budget has run out."""

    def _create(self, **kwargs):
        time.sleep(0.5)
        return super()._create(**kwargs)


def sent_text(fake: FakeAnthropic) -> str:
    return json.dumps(fake.calls[0], default=str)


def test_spoken_digit_runs_are_redacted():
    assert redact_for_prompt("my card is four five six seven eight nine") == "my card is [number]"


def test_numerals_read_in_comma_groups_are_one_redacted_run():
    out = redact_for_prompt("it is 4111, 1111, 1111, 1111 okay")
    leaked = any(char.isdigit() for char in out)
    assert leaked is False
    assert "[number]" in out


def test_short_numbers_never_reach_the_request():
    fake = FakeAnthropic()
    transcript = [
        chunk("the security code is 739", 4.0),
        chunk("and my pin is four eight one five", 8.0),
    ]
    make_explainer(fake).explain(transcript, 0.9)
    sent = sent_text(fake)
    leaked = "739" in sent or "four eight" in sent
    assert leaked is False


def test_digits_read_one_at_a_time_between_words_are_redacted_too():
    fake = FakeAnthropic()
    text = "four okay then one okay then one okay then one okay then two okay then three"
    make_explainer(fake).explain([chunk(text, 4.0)], 0.9)
    sent = sent_text(fake)
    leaked = "four okay" in sent or "then two" in sent
    assert leaked is False


SLOW_PIN = "my pin is 4, then 9, then 1, then 7"
NUMBER_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty "
    "sixty seventy eighty ninety"
).split()


def holds_a_number(text: str) -> bool:
    words = re.findall(r"[a-z]+", text.lower().replace("[number]", " "))
    return any(char.isdigit() for char in text) or any(word in NUMBER_WORDS for word in words)


def test_a_pin_read_one_digit_at_a_time_leaves_no_digit_in_the_prompt():
    # Four lone digits with a word between each: under the old 2+ rule all four stayed.
    out = redact_for_prompt(SLOW_PIN)
    assert out == "my pin is [number], then [number], then [number], then [number]"
    assert holds_a_number(out) is False


def test_the_same_pin_spoken_leaves_no_number_word_in_the_prompt():
    out = redact_for_prompt("my pin is four, then nine, then one, then seven")
    assert out == "my pin is [number], then [number], then [number], then [number]"
    assert holds_a_number(out) is False


@pytest.mark.parametrize("word", NUMBER_WORDS)
def test_every_number_word_is_replaced_on_its_own(word):
    assert redact_for_prompt(f"she said {word} to him") == "she said [number] to him"


def test_the_slow_pin_never_reaches_the_request():
    fake = FakeAnthropic()
    make_explainer(fake).explain([chunk(SLOW_PIN, 4.0)], 0.9)
    asked = fake.calls[0]["messages"][0]["content"]
    said = asked.split("<transcript>", 1)[1].split("</transcript>", 1)[0].strip()
    assert said == "my pin is [number], then [number], then [number], then [number]"


@pytest.mark.parametrize(
    ("heard", "sent"),
    [
        # An "oh" at the edge of a number is a zero, even across a comma or a full stop.
        pytest.param("Four. Nine. One. Oh.", "[number].", id="oh-after-a-full-stop"),
        pytest.param("It is oh, seven, three, four", "It is [number]", id="oh-before-a-comma"),
        pytest.param("double oh, seven", "[number]", id="double-oh-before-a-comma"),
        # Plurals say which digit as plainly as the digit does.
        pytest.param(
            "two sevens and two nines",
            "[number] [number] and [number] [number]",
            id="plurals",
        ),
        pytest.param("nought point five", "[number] point [number]", id="nought"),
        # Digit characters that are not 0-9.
        pytest.param("x² and ①", "x[number] and [number]", id="other-digit-characters"),
    ],
)
def test_what_the_digit_counter_leaves_alone_is_still_replaced_in_the_prompt(heard, sent):
    out = redact_for_prompt(heard)
    assert out == sent
    assert holds_a_number(out) is False


def test_an_oh_with_no_number_in_its_run_stays_in_the_prompt():
    # The limit docs/SPEC.md §5 writes down: it cannot be told from the exclamation.
    assert redact_for_prompt("oh, really") == "oh, really"
    assert redact_for_prompt("four, then oh, then nine") == "[number], then oh, then [number]"


REAL_ORGS = load_orgs()
LISTED = [name for org in REAL_ORGS.values() for name in (org.name, *org.aliases)]


def test_an_organisation_from_the_list_is_named_whole_in_the_prompt():
    # "one" is a number word, and "Capital One" is in the list the model matches against.
    fake = FakeAnthropic()
    said = "This is the Capital One fraud department, read me the code 4, then 9, then 1"
    Explainer(client=fake, orgs=REAL_ORGS).explain([chunk(said, 4.0)], 0.9)
    asked = fake.calls[0]["messages"][0]["content"]
    assert "This is the Capital One fraud department" in asked
    assert "read me the code [number], then [number], then [number]" in asked
    assert "- capital_one: Capital One" in fake.calls[0]["system"]


@pytest.mark.parametrize("name", LISTED)
def test_every_name_and_alias_in_the_list_reaches_the_model_as_it_was_said(name):
    said = f"this is {name} calling about your account"
    assert redact_for_prompt(said, LISTED) == said


@pytest.mark.parametrize(
    ("heard", "sent"),
    [
        pytest.param("capital one called, press one", "capital one called, press [number]", id="lower-case"),
        pytest.param("the code is four Capital One", "the code is [number] Capital One", id="number-before"),
        # A number that runs on from the name may be a code, so the whole of it goes.
        pytest.param("Capital One two three four", "Capital [number]", id="runs-on"),
        pytest.param("Capital One. 4111 1111", "Capital [number]", id="runs-on-past-a-full-stop"),
        pytest.param("double Capital One oh", "double Capital [number]", id="oh-after"),
        pytest.param("the Capital Ones", "the Capital [number]", id="not-the-name"),
    ],
)
def test_only_the_name_itself_is_spared(heard, sent):
    assert redact_for_prompt(heard, LISTED) == sent


def test_without_the_list_no_name_is_spared():
    assert redact_for_prompt("This is Capital One") == "This is Capital [number]"
    assert redact_for_prompt("This is Capital One", ["Chase", "Medicare"]) == "This is Capital [number]"


def test_the_stricter_prompt_rule_does_not_change_what_the_screen_or_the_counter_sees():
    # Detection and the wire keep the old reading of an "oh" beside a comma.
    heard = "I counted four. Oh, I forgot the two sevens."
    assert redact_outbound(heard) == heard
    assert [run.digit_count for run in find_number_runs(heard)] == [1, 1]
    assert redact_for_prompt(heard) == "I counted [number], I forgot the [number] [number]."


def test_a_lone_one_is_replaced_in_the_prompt_too():
    # The screen keeps "this one" (docs/SPEC.md §3). The prompt does not: every number goes.
    fake = FakeAnthropic()
    make_explainer(fake).explain([chunk("I will take this one, thank you", 4.0)], 0.9)
    sent = sent_text(fake)
    assert "this [number], thank you" in sent
    assert "this one" not in sent


def test_only_the_last_minute_is_sent():
    fake = FakeAnthropic()
    transcript = [chunk("walrus at the start", 4.0), chunk("pelican at the end", 70.0)]
    make_explainer(fake).explain(transcript, 0.9)
    sent = sent_text(fake)
    assert "pelican" in sent
    assert "walrus" not in sent


def test_a_slow_model_degrades_inside_the_budget():
    explainer = Explainer(client=SlowAnthropic(), orgs=ORGS, timeout_s=0.05)
    started = time.monotonic()
    result = explainer.explain(TRANSCRIPT, 0.9)
    elapsed = time.monotonic() - started
    assert result.degraded is True
    assert result.safe_exit_line == GENERIC_SAFE_EXIT
    assert elapsed < 0.4
    assert explainer.last_code == "timeout"


def test_nothing_from_the_call_or_the_reply_is_logged(caplog):
    caplog.set_level(logging.DEBUG)
    transcript = [chunk("zebra pineapple 4111 1111 1111 1111", 4.0)]
    fakes = [
        FakeAnthropic(text="walrus is not json"),
        FakeAnthropic(raises=RuntimeError("zebra walrus")),
    ]
    for fake in fakes:
        make_explainer(fake).explain(transcript, 0.9)
    logged = caplog.text
    leaked = any(word in logged for word in ("zebra", "pineapple", "walrus", "4111"))
    assert leaked is False
    assert "explainer degraded: bad_json" in logged
    assert "explainer degraded: request_failed:RuntimeError" in logged


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"reason": "x" * 121}, id="reason-too-long"),
        pytest.param({"reason": "Asked to read 4111 1111 1111 1111 aloud."}, id="digits-in-reason"),
        pytest.param({"claimed_org": "paypal"}, id="org-not-in-the-list"),
        pytest.param({"safe_exit_line": "ok"}, id="line-too-short"),
        pytest.param({"safe_exit_line": "y" * 161}, id="line-too-long"),
        pytest.param({"safe_exit_line": "Read back four one one one."}, id="spoken-number-in-line"),
    ],
)
def test_a_reply_that_breaks_a_rule_degrades(change):
    text = json.dumps({**json.loads(VALID), **change})
    result = make_explainer(FakeAnthropic(text=text)).explain(TRANSCRIPT, 0.9)
    assert result.degraded is True
    assert result.safe_exit_line == GENERIC_SAFE_EXIT
    assert result.official_number is None


def test_a_reply_inside_a_code_fence_still_parses():
    fenced = f"```json\n{VALID}\n```"
    result = make_explainer(FakeAnthropic(text=fenced)).explain(TRANSCRIPT, 0.9)
    assert result.degraded is False
    assert result.scam_type == "gift_card"


def test_without_an_api_key_there_is_no_request(monkeypatch):
    keyless = dataclasses.replace(get_settings(), anthropic_api_key=None)
    monkeypatch.setattr("server.explainer.get_settings", lambda: keyless)
    explainer = Explainer(client=None, orgs=ORGS)
    result = explainer.explain(TRANSCRIPT, 0.9)
    assert result.degraded is True
    assert explainer.last_code == "no_api_key"
