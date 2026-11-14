"""The live socket end to end, with fakes for Whisper, the scorer, Anthropic and ntfy.

Background answers arrive when they arrive, so these tests read until what they are
waiting for has come, and assert order only where the order is a rule.
"""

from __future__ import annotations

import json
import logging
import threading

from server.notify import CODE_TITLE, SCAM_TITLE
from tests.conftest import Harness, scripted
from tests.helpers import (
    FakeAnthropic,
    FakeTranscriber,
    send_audio,
    silence_frame,
    spoken_chunk,
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


def test_a_call_that_escalates_sends_both_alerts_each_before_its_explainer():
    harness = scripted(["hi grandma", "send bail money", "buy gift cards now"], [0.6, 0.9, 0.9])
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            for _ in range(3):
                send_audio(ws, spoken_chunk())
            # Not just the first explainer: both alerts, and both of their answers.
            messages = read_until(ws, both(has("alert", 2), has("explainer", 2)))

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
            read_until(ws, has("explainer", 2), messages)

    assert wait_for(lambda: harness.http.titles() == [SCAM_TITLE])


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
            messages = read_until(ws, both(has("risk", 3), has("explainer", 2)))

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


def test_a_whisper_failure_keeps_the_socket_open_and_the_clock_moving(caplog):
    harness = Harness(transcriber=FakeTranscriber(raises=RuntimeError("4111 1111 1111 1111")))
    with caplog.at_level(logging.WARNING), harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            send_audio(ws, spoken_chunk())
            messages = read_until(ws, has("ack", 1))
            ws.send_bytes(silence_frame())
            read_until(ws, has("ack", 2), messages)

    assert {m["type"] for m in messages} == {"ack"}
    assert "RuntimeError" in caplog.text
    leaked = "4111" in caplog.text
    assert leaked is False  # a class name is logged, never the message


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
