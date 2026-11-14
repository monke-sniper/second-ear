"""The live socket end to end, with fakes for Whisper, the scorer, Anthropic and ntfy.

Background answers arrive when they arrive, so these tests read until what they are
waiting for has come, and assert order only where the order is a rule.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Sequence

import pytest

from server.contracts import FRAME_BYTES, TranscriptChunk
from server.live import LiveCall
from server.notify import CODE_TITLE, SCAM_TITLE
from tests.conftest import Harness, scripted
from tests.helpers import (
    FakeAnthropic,
    FakeHttp,
    FakeTranscriber,
    ScriptedScorer,
    send_audio,
    silence_frame,
    spoken_chunk,
    tone_frame,
    wait_for,
)

MAX_MESSAGES = 200
CARD = "four one one one two two two two three three three three"


def read_until(ws, done, messages=None):
    """Keep reading until `done(messages)` is true. Fails rather than hangs."""
    messages = [] if messages is None else messages
    while not done(messages):
        assert len(messages) < MAX_MESSAGES, "the events never arrived"
        messages.append(ws.receive_json())
    return messages


def of_type(messages, kind):
    return [message for message in messages if message["type"] == kind]


def has(kind, count):
    return lambda messages: len(of_type(messages, kind)) >= count


def both(first, second):
    return lambda messages: first(messages) and second(messages)


def answered(level):
    """True once the alert at `level` and the explainer answer stamped with its time are in."""

    def done(messages):
        times = {m["t_s"] for m in of_type(messages, "alert") if m["level"] == level}
        return any(m["t_s"] in times for m in of_type(messages, "explainer"))

    return done


def test_a_call_that_escalates_sends_both_alerts_each_before_its_explainer():
    harness = scripted(["hi grandma", "send bail money", "buy gift cards now"], [0.6, 0.9, 0.9])
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            send_audio(ws, spoken_chunk())
            # The caution answer has to land before the call escalates: once the scam
            # alert is out, a caution answer is stale and is not sent.
            messages = read_until(ws, has("explainer", 1))
            for _ in range(2):
                send_audio(ws, spoken_chunk())
            read_until(ws, both(has("alert", 2), has("explainer", 2)), messages)

    alerts = of_type(messages, "alert")
    assert [(a["level"], a["trigger"]) for a in alerts] == [
        ("caution", "smoothed_risk"),
        ("scam", "two_high_chunks"),
    ]
    assert [a["t_s"] for a in alerts] == [2.5, 7.5]
    for alert in alerts:
        answer = next(m for m in of_type(messages, "explainer") if m["t_s"] == alert["t_s"])
        assert messages.index(alert) < messages.index(answer)
        assert answer["degraded"] is False and answer["scam_type"] == "grandparent"

    assert [m["text"] for m in of_type(messages, "transcript")] == [
        "hi grandma", "send bail money", "buy gift cards now",
    ]  # fmt: skip
    assert [m["level"] for m in of_type(messages, "risk")] == ["caution", "caution", "scam"]
    assert of_type(messages, "ack")[-1]["total"] == 3 * len(spoken_chunk())
    assert len(harness.anthropic.calls) == 2
    # One scam push, sent after its explainer answered; caution pushes nothing.
    assert wait_for(lambda: harness.http.titles() == [SCAM_TITLE])


def test_the_alert_does_not_wait_for_a_slow_explainer():
    gate = threading.Event()
    harness = scripted(["a", "b"], [0.9, 0.9], anthropic=FakeAnthropic(gate=gate))
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            send_audio(ws, spoken_chunk())
            send_audio(ws, spoken_chunk())
            messages = read_until(ws, has("alert", 2))  # the explainer is still held
            assert of_type(messages, "explainer") == []

            gate.set()
            read_until(ws, answered("scam"), messages)

    assert wait_for(lambda: harness.http.titles() == [SCAM_TITLE])


def test_a_slow_caution_answer_is_never_sent_once_the_scam_alert_is_out():
    gate = threading.Event()
    anthropic = FakeAnthropic(gate=gate, held=1)  # only the first request is slow
    harness = scripted(["a", "b"], [0.9, 0.9], anthropic=anthropic)
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            send_audio(ws, spoken_chunk())
            assert wait_for(lambda: len(anthropic.calls) == 1)  # the caution request is held
            send_audio(ws, spoken_chunk())
            messages = read_until(ws, answered("scam"))  # the scam alert and its answer

            gate.set()  # the caution answer comes back now, with nowhere to go
            assert wait_for(lambda: len(anthropic.finished) == 2)
            for _ in range(3):  # give a wrongly sent answer every chance to show up
                ws.send_bytes(silence_frame())
            read_until(ws, has("ack", 23), messages)

        assert wait_for(lambda: harness.http.titles() == [SCAM_TITLE])

    caution, scam = of_type(messages, "alert")
    assert (caution["level"], scam["level"]) == ("caution", "scam")
    assert caution["t_s"] != scam["t_s"]
    assert [m["t_s"] for m in of_type(messages, "explainer")] == [scam["t_s"]]


def test_silent_audio_is_acked_and_never_reaches_whisper():
    harness = scripted(["should not be heard"], [0.9])
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            for _ in range(16):  # 4 s of silence: two all-quiet chunks
                ws.send_bytes(silence_frame())
            messages = read_until(ws, has("ack", 16))

            send_audio(ws, spoken_chunk())
            read_until(ws, has("risk", 1), messages)

    assert harness.transcriber.calls == [len(spoken_chunk())]  # only the spoken chunk
    assert len(of_type(messages, "transcript")) == 1
    # The quiet chunks still moved the clock: 4 s of silence, then a 2.5 s chunk.
    assert of_type(messages, "transcript")[0]["t_s"] == 6.5


def test_a_code_read_aloud_sends_one_warning_one_push_and_no_digits():
    harness = scripted(["read me the code", CARD, CARD], [0.9])
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            for _ in range(3):
                send_audio(ws, spoken_chunk())
            messages = read_until(ws, both(has("risk", 3), answered("scam")))

    assert [d["digit_count"] for d in of_type(messages, "danger")] == [12]
    assert wait_for(lambda: sorted(harness.http.titles()) == sorted([SCAM_TITLE, CODE_TITLE]))
    sent = json.dumps([m for m in messages if m["type"] != "ack"]) + json.dumps(harness.http.posts)
    leaked = "four one one" in sent or "4111" in sent
    assert leaked is False


def test_reset_starts_a_new_call_and_drops_the_late_answer():
    gate = threading.Event()
    anthropic = FakeAnthropic(gate=gate)
    harness = scripted(["a", "b", "c"], [0.9, 0.9, 0.1], anthropic=anthropic)
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            send_audio(ws, spoken_chunk())
            send_audio(ws, spoken_chunk())
            messages = read_until(ws, has("alert", 2))  # both explainers are held

            ws.send_text('{"type": "reset"}')
            ws.send_bytes(silence_frame())
            after = read_until(ws, has("ack", 1))
            assert after[-1]["total"] == len(silence_frame())

            gate.set()  # the old call's answers come back now, too late
            assert wait_for(lambda: len(anthropic.calls) == 2 and anthropic.done.is_set())
            for _ in range(3):  # give the dropped answers every chance to show up
                ws.send_bytes(silence_frame())
            read_until(ws, has("ack", 4), after)

            send_audio(ws, spoken_chunk())
            read_until(ws, has("risk", 1), after)

    assert of_type(messages + after, "explainer") == []
    assert harness.http.posts == []  # the old call's scam push was dropped with it
    assert of_type(after, "transcript")[0]["t_s"] == 3.5  # the clock restarted
    assert of_type(after, "alert") == []


def test_a_hang_up_still_sends_the_scam_push():
    gate = threading.Event()
    harness = scripted(["a", "b"], [0.9, 0.9], anthropic=FakeAnthropic(gate=gate))
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            send_audio(ws, spoken_chunk())
            send_audio(ws, spoken_chunk())
            read_until(ws, has("alert", 2))
            threading.Timer(0.2, gate.set).start()  # the answer lands after the close

        assert wait_for(lambda: harness.http.titles() == [SCAM_TITLE])


def test_a_whisper_failure_is_reported_once_and_the_clock_keeps_moving(caplog):
    transcriber = FakeTranscriber(["back again"], raises=RuntimeError("4111 1111 1111 1111"))
    harness = Harness(transcriber=transcriber)
    with caplog.at_level(logging.WARNING), harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            for _ in range(2):
                send_audio(ws, spoken_chunk())
            ws.send_bytes(silence_frame())
            # The ack for the frame after them: both chunks have been through Whisper.
            messages = read_until(ws, has("ack", 21))
            assert {m["type"] for m in messages} == {"ack", "error"}

            transcriber.raises = None  # Whisper is back
            send_audio(ws, spoken_chunk())
            read_until(ws, has("transcript", 1), messages)

    # Two chunks failed; the client is told once, in fixed words.
    assert of_type(messages, "error") == [
        {"type": "error", "detail": "could not process that audio"}
    ]
    assert transcriber.calls[:2] == [len(spoken_chunk())] * 2
    # The unread chunks moved the clock: 2.5 s twice, then the quiet frame and this chunk.
    assert of_type(messages, "transcript")[0]["t_s"] == 7.75
    assert "transcribe failed: RuntimeError" in caplog.text
    leaked = "4111" in caplog.text
    assert leaked is False  # a class name is logged, never the message


def test_a_new_call_reports_its_own_whisper_failure():
    harness = Harness(transcriber=FakeTranscriber(raises=RuntimeError("no model")))
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            send_audio(ws, spoken_chunk())
            ws.send_bytes(silence_frame())
            messages = read_until(ws, has("ack", 11))

            ws.send_text('{"type": "reset"}')
            send_audio(ws, spoken_chunk())
            ws.send_bytes(silence_frame())
            read_until(ws, has("ack", 22), messages)

    assert len(of_type(messages, "error")) == 2  # once per call, and this was two calls


# ------------------------------------------------------------ the end of a call


def test_a_code_read_in_the_last_second_and_a_half_still_warns_the_family():
    harness = scripted(["read me the code", CARD], [0.6])
    tail = tone_frame() * 6  # 1.5 s of speech, cut off before any pause
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            send_audio(ws, spoken_chunk())
            send_audio(ws, tail)
            messages = read_until(ws, has("ack", 16))  # every frame reached the server
            assert of_type(messages, "danger") == []  # the code is not in a chunk yet

        # The socket is closed. The tail is transcribed, the warning fires, one push.
        assert wait_for(lambda: harness.http.titles() == [CODE_TITLE])

    assert harness.transcriber.calls == [len(spoken_chunk()), len(tail)]


class FakeSocket:
    """Hands `LiveCall` its messages and then a disconnect, and keeps what was sent.

    The test client cancels the socket handler as it closes the socket. These tests
    run the handler on their own loop instead, so it reaches its end the way it does
    under uvicorn, where a hang-up cancels nothing.
    """

    def __init__(self, messages: Sequence[bytes]) -> None:
        self._incoming = [{"type": "websocket.receive", "bytes": data} for data in messages]
        self._incoming.append({"type": "websocket.disconnect"})
        self.sent: list[dict] = []

    async def receive(self) -> dict:
        return self._incoming.pop(0)

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


def run_call(harness: Harness, pcm: bytes) -> tuple[list[dict], list[str]]:
    """One whole call: every frame of `pcm`, the hang-up, and the handler to its end.

    Returns what went out on the socket, and the push titles at the moment `run()`
    came back: read before the loop is torn down, which would let a late push finish.
    """
    frames = [pcm[start : start + FRAME_BYTES] for start in range(0, len(pcm), FRAME_BYTES)]
    socket = FakeSocket(frames)
    titles: list[str] = []

    async def serve() -> None:
        await LiveCall(socket, harness.services()).run()
        titles.extend(harness.http.titles())

    asyncio.run(serve())
    return socket.sent, titles


class SlowHttp(FakeHttp):
    """A push that takes a moment, so a handler that does not wait for it is caught."""

    def post(self, url, **kwargs):
        time.sleep(0.05)
        return super().post(url, **kwargs)


def test_the_handler_does_not_return_until_the_tail_and_its_push_are_done():
    harness = scripted(["read me the code", CARD], [0.6], http=SlowHttp())
    tail = tone_frame() * 6

    sent, titles = run_call(harness, spoken_chunk() + tail)

    assert titles == [CODE_TITLE]  # already sent when `run()` came back
    assert harness.transcriber.calls == [len(spoken_chunk()), len(tail)]
    assert of_type(sent, "danger") == []  # nobody is left on the socket to send it to


@pytest.mark.parametrize(
    ("tail", "heard"),
    [
        (tone_frame() * 1, False),  # 0.25 s: under the half-second floor
        (tone_frame() * 2, True),  # 0.5 s: at the floor
        (silence_frame() * 4, False),  # 1 s, but nothing in it
    ],
)
def test_only_a_tail_of_half_a_second_with_sound_in_it_is_transcribed(tail, heard):
    harness = scripted(["hello there", "one more thing"], [0.1])

    run_call(harness, spoken_chunk() + tail)

    expected = [len(spoken_chunk()), len(tail)] if heard else [len(spoken_chunk())]
    assert harness.transcriber.calls == expected
    assert harness.http.posts == []


def test_a_caution_raised_by_the_tail_asks_no_explainer():
    harness = scripted(["hello there", "send the money"], [0.2, 0.9])

    _sent, titles = run_call(harness, spoken_chunk() + tone_frame() * 6)

    assert len(harness.scorer.calls) == 2  # the tail was scored: smoothed risk 0.55, caution
    assert harness.anthropic.calls == []  # an answer would have nowhere to go
    assert titles == []


def test_a_scam_raised_by_the_tail_is_explained_and_pushed():
    harness = scripted(["a", "b"], [0.9])

    _sent, titles = run_call(harness, spoken_chunk() + tone_frame() * 6)

    assert titles == [SCAM_TITLE]
    assert len(harness.anthropic.calls) == 2  # the caution during the call, the scam after


class HeldTranscriber(FakeTranscriber):
    """Stays inside `transcribe` until released, and notes how many calls overlap."""

    def __init__(self, texts: Sequence[str]) -> None:
        super().__init__(texts)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.most_inside = 0
        self._inside = 0
        self._counting = threading.Lock()

    def transcribe(self, pcm: bytes, *, start_s: float = 0.0) -> TranscriptChunk:
        with self._counting:
            self._inside += 1
            self.most_inside = max(self.most_inside, self._inside)
        self.entered.set()
        try:
            self.release.wait(timeout=3.0)
            return super().transcribe(pcm, start_s=start_s)
        finally:
            with self._counting:
                self._inside -= 1


def test_a_handler_cancelled_mid_chunk_keeps_the_tail_out_of_whisper_until_it_is_done():
    transcriber = HeldTranscriber(["a", "b"])
    harness = Harness(transcriber=transcriber, scorer=ScriptedScorer([0.1]))
    # The second message closes a 2 s chunk and leaves 1.5 s behind it for the tail.
    tail = tone_frame() * 6
    socket = FakeSocket([tone_frame() * 6, silence_frame() * 2 + tail])

    async def serve() -> None:
        running = asyncio.create_task(LiveCall(socket, harness.services()).run())
        assert await asyncio.to_thread(transcriber.entered.wait, 3.0)  # the chunk is in Whisper
        running.cancel()
        await asyncio.sleep(0.2)  # the tail has every chance to barge in
        transcriber.release.set()
        await asyncio.gather(running, return_exceptions=True)

    asyncio.run(serve())

    assert transcriber.most_inside == 1
    assert transcriber.calls == [8 * FRAME_BYTES, len(tail)]


def test_startup_warms_whisper_in_the_background():
    harness = Harness()
    with harness.client() as client:
        assert harness.transcriber.warmed.wait(timeout=3.0)
        assert client.get("/health").status_code == 200


def test_a_failed_warmup_is_logged_and_the_server_still_answers(caplog):
    harness = Harness(transcriber=FakeTranscriber(raises=OSError("cuda missing")))
    with caplog.at_level(logging.WARNING), harness.client() as client:
        assert harness.transcriber.warmed.wait(timeout=3.0)
        assert client.get("/health").json() == {"status": "ok"}
        assert wait_for(lambda: "whisper warmup failed: OSError" in caplog.text)
