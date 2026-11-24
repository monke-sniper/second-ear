"""The explainer's round trip to the page, on the live socket.

With Firebase set up, an alert sends the page an `explain` request and the page's
`explained` answer becomes the `explainer` event. A plain test client plays the page
here; no browser, no Firebase and no model is involved.
"""

from __future__ import annotations

import json
import time

from server.config import FirebaseSettings
from server.explainer import GENERIC_SAFE_EXIT
from server.notify import SCAM_TITLE
from tests.conftest import Harness, scripted
from tests.helpers import EXPLAINER_REPLY, send_audio, silence_frame, spoken_chunk, tone_frame, wait_for
from tests.test_ws_live import answered, has, of_type, read_until, run_call

FIREBASE = FirebaseSettings(api_key="test-api-key", project_id="second-ear-test", app_id="1:2:web:3")
# Four digits: enough for the prompt to need redacting, too few for the code warning.
PIN = "four nine one seven"


def explained(request_id: int, text: str = EXPLAINER_REPLY, source: str = "on_device") -> str:
    """The page's answer to request `request_id`, as it goes over the socket."""
    return json.dumps({"type": "explained", "id": request_id, "text": text, "source": source})


def test_an_alert_asks_the_page_and_its_answer_becomes_the_explainer_event():
    harness = scripted([f"read me the pin {PIN}", "buy gift cards now"], [0.9, 0.9], firebase=FIREBASE)
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            send_audio(ws, spoken_chunk())
            messages = read_until(ws, has("explain", 1))
            caution_ask = of_type(messages, "explain")[0]
            ws.send_text(explained(caution_ask["id"]))
            read_until(ws, answered("caution"), messages)

            send_audio(ws, spoken_chunk())
            read_until(ws, has("explain", 2), messages)
            scam_ask = of_type(messages, "explain")[1]
            ws.send_text(explained(scam_ask["id"], source="in_cloud"))
            read_until(ws, answered("scam"), messages)

        assert wait_for(lambda: harness.http.titles() == [SCAM_TITLE])

    caution, scam = of_type(messages, "alert")
    assert (caution["level"], scam["level"]) == ("caution", "scam")
    # Each request is stamped with its alert's time and comes after the alert itself.
    assert (caution_ask["t_s"], scam_ask["t_s"]) == (caution["t_s"], scam["t_s"])
    assert messages.index(caution) < messages.index(caution_ask)
    assert caution_ask["id"] != scam_ask["id"]
    # What the page is handed holds no number from the call.
    assert "<transcript>" in caution_ask["prompt"] and "[number]" in caution_ask["prompt"]
    leaked = any(char.isdigit() for char in caution_ask["prompt"]) or "four nine" in caution_ask["prompt"]
    assert leaked is False
    answers = of_type(messages, "explainer")
    assert [a["t_s"] for a in answers] == [caution["t_s"], scam["t_s"]]
    assert all(a["degraded"] is False and a["scam_type"] == "grandparent" for a in answers)
    assert harness.anthropic.calls == []  # the page answered; Haiku was never asked


def test_a_page_that_says_nothing_gets_the_generic_line_when_the_budget_is_spent():
    harness = scripted(["send bail money"], [0.9], firebase=FIREBASE, explainer_timeout_s=0.2)
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            send_audio(ws, spoken_chunk())
            messages = read_until(ws, has("explainer", 1))

    answer = of_type(messages, "explainer")[0]
    assert len(of_type(messages, "explain")) == 1
    assert answer["degraded"] is True and answer["safe_exit_line"] == GENERIC_SAFE_EXIT
    assert harness.anthropic.calls == []


def test_a_page_that_cannot_answer_says_so_and_the_generic_line_comes_at_once():
    harness = scripted(["send bail money"], [0.9], firebase=FIREBASE)
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            send_audio(ws, spoken_chunk())
            messages = read_until(ws, has("explain", 1))
            asked_at = time.monotonic()
            ws.send_text(explained(of_type(messages, "explain")[0]["id"], text="", source="none"))
            read_until(ws, has("explainer", 1), messages)
            waited_s = time.monotonic() - asked_at

    assert of_type(messages, "explainer")[0]["degraded"] is True
    assert waited_s < 2.0  # well inside the 4 s the server would otherwise wait


def test_an_answer_that_fails_the_checks_never_reaches_the_screen():
    harness = scripted(["send bail money"], [0.9], firebase=FIREBASE)
    bad = json.dumps({**json.loads(EXPLAINER_REPLY), "safe_exit_line": "Call 555 0100 instead."})
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            send_audio(ws, spoken_chunk())
            messages = read_until(ws, has("explain", 1))
            ws.send_text(explained(of_type(messages, "explain")[0]["id"], text=bad))
            read_until(ws, has("explainer", 1), messages)

    answer = of_type(messages, "explainer")[0]
    assert answer["degraded"] is True and answer["safe_exit_line"] == GENERIC_SAFE_EXIT
    leaked = "555" in json.dumps(messages)
    assert leaked is False


def test_an_answer_nobody_is_waiting_for_is_dropped_without_a_word():
    harness = scripted(["hello there"], [0.1], firebase=FIREBASE)
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            ws.send_text(explained(99))
            ws.send_bytes(silence_frame())
            messages = read_until(ws, has("ack", 1))

    assert [m["type"] for m in messages] == ["ack"]


def test_a_malformed_answer_gets_an_error_that_echoes_nothing():
    harness = scripted(["hello there"], [0.1], firebase=FIREBASE)
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            ws.send_text('{"type": "explained", "id": "4111 1111 1111 1111"}')
            assert ws.receive_json() == {"type": "error", "detail": "explained message not understood"}

            ws.send_bytes(silence_frame())  # the socket is still open
            assert ws.receive_json()["type"] == "ack"


def test_without_firebase_the_page_is_never_asked():
    harness = scripted(["send bail money"], [0.9])
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            send_audio(ws, spoken_chunk())
            messages = read_until(ws, has("explainer", 1))

    assert of_type(messages, "explain") == []
    assert len(harness.anthropic.calls) == 1


def test_a_slow_caution_answer_from_the_page_is_dropped_once_the_scam_alert_is_out():
    harness = scripted(["a", "b"], [0.9, 0.9], firebase=FIREBASE)
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            send_audio(ws, spoken_chunk())
            send_audio(ws, spoken_chunk())
            messages = read_until(ws, has("explain", 2))
            caution_ask, scam_ask = of_type(messages, "explain")

            ws.send_text(explained(scam_ask["id"]))
            read_until(ws, answered("scam"), messages)
            ws.send_text(explained(caution_ask["id"]))  # late, for an alert that was replaced
            for _ in range(3):  # give a wrongly sent answer every chance to show up
                ws.send_bytes(silence_frame())
            read_until(ws, has("ack", 23), messages)

    assert [m["t_s"] for m in of_type(messages, "explainer")] == [scam_ask["t_s"]]


def test_reset_drops_the_question_the_page_was_still_answering():
    harness = scripted(["a", "b"], [0.9, 0.1], firebase=FIREBASE)
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:
            send_audio(ws, spoken_chunk())
            messages = read_until(ws, has("explain", 1))

            ws.send_text('{"type": "reset"}')
            ws.send_text(explained(of_type(messages, "explain")[0]["id"]))  # for the old call
            for _ in range(3):
                ws.send_bytes(silence_frame())
            after = read_until(ws, has("ack", 3))

    assert of_type(messages + after, "explainer") == []
    assert of_type(after, "error") == []
    assert harness.http.posts == []


def test_after_a_hang_up_the_server_explains_the_scam_for_the_push():
    # The page has gone, so it cannot be asked: the scam the tail raises goes to the
    # server's own explainer, and the family still gets its push.
    harness = scripted(["a", "b"], [0.9], firebase=FIREBASE)

    sent, titles = run_call(harness, spoken_chunk() + tone_frame() * 6)

    assert titles == [SCAM_TITLE]
    assert of_type(sent, "explain") == []  # nothing is asked of a page that is not there
    assert len(harness.anthropic.calls) == 2  # the caution and the scam, both by the server
