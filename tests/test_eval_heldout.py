"""The held-out generator: the slot plan, the format checks and the Gemini client.

Gemini is faked with httpx.MockTransport, so no test reaches the network or needs a key.
Failure messages never print a transcript.
"""

from __future__ import annotations

import json
from collections import Counter

import httpx
import pytest

from eval import make_heldout
from eval.heldout_brief import BRIEF, OPENINGS, SCENARIOS, Slot, build_plan
from eval.heldout_checks import format_problem
from eval.make_heldout import KEY_HEADER, GeminiError, generate
from server.config import get_settings

FILLER = " ".join(["the nurse said the refill is ready whenever you want to come by"] * 8)
STARTS = {"hello": "Hello", "hi": "Hi", "this is": "This is", "none": "Your"}


def good_text(opening: str) -> str:
    return f"{STARTS[opening]} {FILLER}"


def gemini_answer(texts: dict[str, str]) -> dict:
    body = json.dumps({"transcripts": [{"id": key, "text": value} for key, value in texts.items()]})
    return {"candidates": [{"content": {"parts": [{"text": body}]}}], "modelVersion": "gemini-test"}


def requested(request: httpx.Request) -> dict[str, str]:
    """`id -> opening` for the items one request asks for."""
    text = json.loads(request.content)["contents"][0]["parts"][0]["text"]
    slots = {slot.id: slot.opening for slot in build_plan()}
    return {slot_id: opening for slot_id, opening in slots.items() if f'"{slot_id}"' in text}


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_the_plan_is_fifty_fifty_with_the_same_openings_for_both_labels():
    plan = build_plan()
    scam = [slot for slot in plan if slot.label == 1]
    legit = [slot for slot in plan if slot.label == 0]

    assert (len(plan), len(scam), len(legit)) == (100, 50, 50)
    assert len({slot.id for slot in plan}) == 100
    assert Counter(s.opening for s in scam) == Counter(s.opening for s in legit)
    assert set(Counter(s.opening for s in scam)) == set(OPENINGS)
    assert Counter(s.type for s in plan) == {s.type: s.count for s in SCENARIOS}


def test_the_brief_names_no_phrase_from_either_keyword_list():
    import re

    from eval.keyword_baseline import KEYWORDS
    from server.scorer import RED_FLAGS

    phrases = list(KEYWORDS) + [phrase for flag in RED_FLAGS for phrase in flag.phrases]
    found = [p for p in phrases if re.search(rf"\b{re.escape(p)}\b", BRIEF.lower())]

    # The scenario lines are the owner's list and name their subject; the brief itself,
    # which every request carries, must not seed a phrase either scorer looks for.
    assert found == []


@pytest.mark.parametrize(
    ("opening", "text", "problem"),
    [
        ("hello", good_text("hello"), None),
        ("none", good_text("none"), None),
        ("hello", good_text("hi"), "opening"),
        ("none", good_text("hello"), "opening"),
        ("none", good_text("this is"), "opening"),
        ("hi", "Hi there", "length"),
        ("hi", "", "missing"),
        ("hi", f"Hi there. Caller: {FILLER}. Receiver: yes", "labels"),
        ("hi", f"Hi [laughs] {FILLER}", "markup"),
        ("hi", f"Hi the code is four one five nine two six {FILLER}", "numbers"),
        ("hi", f"Hi call 555-0100 {FILLER}", "numbers"),
        ("hi", f"Hi can I borrow $40 or 1,500 dollars {FILLER}", None),
    ],
)
def test_format_checks(opening, text, problem):
    assert format_problem(Slot("x", 1, "prize", opening), text) == problem


def test_generate_fills_every_slot_and_sends_the_key_in_a_header():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=gemini_answer({i: good_text(o) for i, o in requested(request).items()}))

    rows, meta = generate(client_for(handler), "gemini-test", "secret-key", sleep=lambda _s: None)

    assert [row["id"] for row in rows] == [slot.id for slot in build_plan()]
    assert meta["rows"] == 100 and meta["labels"] == {"scam": 50, "legitimate": 50}
    assert meta["openings"]["scam"] == meta["openings"]["legitimate"]
    assert meta["requests"] == len(SCENARIOS) and meta["extra_rounds"] == 0
    assert meta["generator"]["model_versions"] == ["gemini-test"]
    assert all(request.headers[KEY_HEADER] == "secret-key" for request in seen)
    assert not any("secret-key" in str(request.url) for request in seen)
    assert json.loads(seen[0].content)["systemInstruction"]["parts"][0]["text"] == BRIEF
    assert "secret-key" not in json.dumps(meta)


def test_a_transcript_that_fails_the_format_is_asked_for_again():
    calls = Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        wanted = requested(request)
        texts = {i: good_text(o) for i, o in wanted.items()}
        if "scam-prize-01" in wanted and not calls["prize"]:
            texts["scam-prize-01"] = "too short"
        calls["prize"] += "scam-prize-01" in wanted
        return httpx.Response(200, json=gemini_answer(texts))

    rows, meta = generate(client_for(handler), "gemini-test", "k", sleep=lambda _s: None)

    assert len(rows) == 100 and meta["extra_rounds"] == 1
    assert calls["prize"] == 2


def test_generate_stops_when_the_format_never_comes_right():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=gemini_answer({i: "too short" for i in requested(request)}))

    with pytest.raises(GeminiError) as caught:
        generate(client_for(handler), "gemini-test", "k", sleep=lambda _s: None)

    assert "length" in str(caught.value) and "too short" not in str(caught.value)


def test_a_rate_limit_is_waited_out_and_an_error_never_shows_the_key():
    answers = iter([429, 200])
    waits: list[float] = []

    def busy_once(request: httpx.Request) -> httpx.Response:
        if next(answers, 200) == 429:
            return httpx.Response(429, json={"error": {"message": "slow down"}})
        return httpx.Response(200, json=gemini_answer({i: good_text(o) for i, o in requested(request).items()}))

    rows, _meta = generate(client_for(busy_once), "gemini-test", "k", sleep=waits.append)
    assert len(rows) == 100 and len(waits) == 1

    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad key secret-key"}})

    with pytest.raises(GeminiError) as caught:
        generate(client_for(refused), "gemini-test", "secret-key", sleep=lambda _s: None)
    assert "secret-key" not in str(caught.value) and "400" in str(caught.value)


@pytest.fixture()
def with_key(monkeypatch: pytest.MonkeyPatch):
    get_settings.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    yield
    get_settings.cache_clear()


def test_main_writes_the_set_once_and_never_over_an_existing_one(tmp_path, with_key, capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=gemini_answer({i: good_text(o) for i, o in requested(request).items()}))

    out = tmp_path / "heldout" / "gemini.jsonl"
    assert make_heldout.main(["--out", str(out)], client=client_for(handler)) == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 100 and set(rows[0]) == {"id", "label", "type", "opening", "text"}
    assert json.loads(out.with_suffix(".meta.json").read_text(encoding="utf-8"))["rows"] == 100

    before = out.read_bytes()
    assert make_heldout.main(["--out", str(out)], client=client_for(handler)) == 2
    assert out.read_bytes() == before
    assert "secret-key" not in capsys.readouterr().out


def test_main_writes_nothing_when_the_run_fails(tmp_path, with_key):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "no"}})

    out = tmp_path / "gemini.jsonl"
    assert make_heldout.main(["--out", str(out)], client=client_for(handler)) == 1
    assert not out.exists() and not out.with_suffix(".meta.json").exists()
