"""The hallucination guard in server/stt.py, with a fake in place of faster-whisper.

The fake returns segments with the three fields faster-whisper puts on every segment.
The bug this pins: on a near-silent call Whisper wrote a repetition loop, the scorer rated
it high, and a caution went up. No test loads Whisper.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from eval.replay import replay_call
from server import stt
from server.stt import DROP_NO_SPEECH, DROP_REPETITION, StreamTranscriber, drop_reason
from tests.helpers import tone_frame

LOOP = "a little bit of a little bit of a little bit of a little bit of"


def segment(text: str = " fine", *, ratio: float = 1.3, no_speech: float = 0.05, logprob: float = -0.3):
    return SimpleNamespace(text=text, compression_ratio=ratio, no_speech_prob=no_speech, avg_logprob=logprob)


class FakeModel:
    def __init__(self, segments) -> None:
        self.segments = list(segments)

    def transcribe(self, audio, **kwargs):
        return iter(self.segments), SimpleNamespace(language="en")


def transcriber_saying(*segments) -> StreamTranscriber:
    return StreamTranscriber(model_factory=lambda size, device, compute: FakeModel(segments))


class RatesEverythingHigh:
    """The scorer in the bug report: any text at all scores 0.98."""

    name = "fake-scorer"

    def score(self, transcript: str) -> float:
        return 0.98 if transcript.strip() else 0.0


def test_the_thresholds_are_whisper_s_reference_values():
    assert (stt.MAX_COMPRESSION_RATIO, stt.MAX_NO_SPEECH_PROB, stt.MIN_AVG_LOGPROB) == (2.4, 0.6, -1.0)


def test_a_repetition_loop_is_dropped_and_the_rest_of_the_chunk_is_kept():
    transcriber = transcriber_saying(segment(" hello"), segment(f" {LOOP}", ratio=9.5))

    result = transcriber.transcribe(tone_frame() * 8)

    assert result.text == "hello"


def test_a_chunk_that_is_only_a_hallucination_comes_back_empty():
    assert transcriber_saying(segment(f" {LOOP}", ratio=9.5)).transcribe(tone_frame() * 8).text == ""


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        pytest.param({"ratio": 2.41}, DROP_REPETITION, id="ratio-just-over"),
        pytest.param({"ratio": 2.4}, None, id="ratio-at-the-line-is-kept"),
        pytest.param({"no_speech": 0.7, "logprob": -1.2}, DROP_NO_SPEECH, id="made-up-over-silence"),
        pytest.param({"no_speech": 0.7, "logprob": -0.5}, None, id="quiet-but-confident-is-kept"),
        pytest.param({"no_speech": 0.3, "logprob": -1.5}, None, id="unsure-but-speech-is-kept"),
        pytest.param({"no_speech": 0.6, "logprob": -1.5}, None, id="no-speech-at-the-line-is-kept"),
        pytest.param({"no_speech": 0.7, "logprob": -1.0}, None, id="logprob-at-the-line-is-kept"),
        pytest.param({"ratio": 3.0, "no_speech": 0.7, "logprob": -1.2}, DROP_REPETITION, id="both-fail"),
    ],
)
def test_the_two_rules_and_their_edges(fields, reason):
    assert drop_reason(segment(**fields)) == reason


def test_a_segment_without_the_fields_is_kept():
    assert drop_reason(SimpleNamespace(text=" hello")) is None
    assert drop_reason(SimpleNamespace(text=" hello", no_speech_prob=0.9)) is None


def test_a_drop_is_logged_by_its_reason_code_and_nothing_else(caplog):
    caplog.set_level(logging.DEBUG)
    transcriber = transcriber_saying(
        segment(" zebra zebra zebra", ratio=9.5), segment(" walrus", no_speech=0.9, logprob=-1.4)
    )

    transcriber.transcribe(tone_frame() * 8)

    messages = [record.getMessage() for record in caplog.records if record.name == "second_ear.stt"]
    assert messages == [f"whisper segment dropped: {DROP_REPETITION}", f"whisper segment dropped: {DROP_NO_SPEECH}"]
    leaked = any(word in caplog.text for word in ("zebra", "walrus"))
    assert leaked is False


def test_warmup_does_not_log_what_it_drops(caplog):
    caplog.set_level(logging.DEBUG)
    transcriber = transcriber_saying(segment(" thank you", no_speech=0.9, logprob=-1.4))

    transcriber.warmup()

    assert [record for record in caplog.records if record.name == "second_ear.stt"] == []


def test_a_near_silent_call_with_a_repetition_loop_raises_no_alert():
    """The reported bug, end to end: chunker, transcriber, session and alert rules."""
    spoken = tone_frame() * 8 + bytes(len(tone_frame())) * 2  # one 2.5 s chunk, then a pause
    transcriber = transcriber_saying(segment(f" {LOOP}", ratio=9.5))

    replay = replay_call(spoken * 3, transcriber, RatesEverythingHigh())

    assert len(replay.steps) == 3
    assert all(step.transcript is None and step.alert is None for step in replay.steps)
    assert replay.chunks == ()


def test_without_the_guard_the_same_call_would_have_alerted(monkeypatch):
    """The control: the test above passes because of the guard, not because of the fakes."""
    monkeypatch.setattr(stt, "drop_reason", lambda segment: None)
    spoken = tone_frame() * 8 + bytes(len(tone_frame())) * 2
    transcriber = transcriber_saying(segment(f" {LOOP}", ratio=9.5))

    replay = replay_call(spoken * 3, transcriber, RatesEverythingHigh())

    assert any(step.alert is not None for step in replay.steps)
