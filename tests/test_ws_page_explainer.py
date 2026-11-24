"""The explainer's round trip to the page, on the live socket.

With Firebase set up, an alert sends the page an `explain` request and the page's
`explained` answer becomes the `explainer` event. A plain test client plays the page
here; no browser, no Firebase and no model is involved.
"""

from __future__ import annotations

import asyncio
import json
import time

from server.config import FirebaseSettings
from server.contracts import FRAME_BYTES
from server.explainer import GENERIC_SAFE_EXIT
from server.live import LiveCall, Services
from server.notify import SCAM_TITLE
from tests.conftest import Harness, scripted
from tests.helpers import (
    EXPLAINER_REPLY,
    ScriptedScorer,
    send_audio,
    silence_frame,
    spoken_chunk,
    tone_frame,
    wait_for,
)
from tests.test_ws_live import HeldTranscriber, answered, has, of_type, read_until

FIREBASE = FirebaseSettings(api_key="test-api-key", project_id="second-ear-test", app_id="1:2:web:3")
# Four digits: enough for the prompt to need redacting, too few for the code warning.
PIN = "four nine one seven"
# What a browser sends when the page was served by this server: the Origin is the Host.
OWN_PAGE = {"Origin": "http://localhost:8000", "Host": "localhost:8000"}
WAIT_S = 3.0


def page(client, headers=OWN_PAGE):
    """The audio socket, opened the way the app's own page opens it."""
    return client.websocket_connect("/ws/audio", headers=headers)


def explained(request_id: int, text: str = EXPLAINER_REPLY, source: str = "on_device") -> str:
    """The page's answer to request `request_id`, as it goes over the socket."""
    return json.dumps({"type": "explained", "id": request_id, "text": text, "source": source})


def test_an_alert_asks_the_page_and_its_answer_becomes_the_explainer_event():
    harness = scripted([f"read me the pin {PIN}", "buy gift cards now"], [0.9, 0.9], firebase=FIREBASE)
    with harness.client() as client:
        with page(client) as ws:
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


def test_an_answer_is_taken_while_the_next_chunk_is_still_in_whisper():
    # The page's answer must not queue behind audio that is waiting for Whisper: on a
    # slow laptop that wait alone could eat the 4 s budget.
    transcriber = HeldTranscriber(["send bail money", "buy gift cards now"])
    harness = Harness(transcriber=transcriber, scorer=ScriptedScorer([0.6, 0.6]), firebase=FIREBASE)
    with harness.client() as client:
        with page(client) as ws:
            send_audio(ws, spoken_chunk())
            assert transcriber.entered.wait(WAIT_S)
            transcriber.release.set()  # the first chunk is heard: a caution, and its request
            messages = read_until(ws, has("explain", 1))

            transcriber.release.clear()
            transcriber.entered.clear()
            send_audio(ws, spoken_chunk())
            assert transcriber.entered.wait(WAIT_S)  # the second chunk is in Whisper, held

            asked_at = time.monotonic()
            ws.send_text(explained(of_type(messages, "explain")[0]["id"]))
            read_until(ws, has("explainer", 1), messages)
            waited_s = time.monotonic() - asked_at
            still_in_whisper = not transcriber.release.is_set()
            transcriber.release.set()

    assert of_type(messages, "explainer")[0]["degraded"] is False
    assert still_in_whisper is True
    assert waited_s < 1.5  # the held decode would have kept it for 3 s


def test_a_page_that_says_nothing_gets_the_generic_line_when_the_budget_is_spent():
    harness = scripted(["send bail money"], [0.9], firebase=FIREBASE, explainer_timeout_s=0.2)
    with harness.client() as client:
        with page(client) as ws:
            send_audio(ws, spoken_chunk())
            messages = read_until(ws, has("explainer", 1))

    answer = of_type(messages, "explainer")[0]
    assert len(of_type(messages, "explain")) == 1
    assert answer["degraded"] is True and answer["safe_exit_line"] == GENERIC_SAFE_EXIT
    assert harness.anthropic.calls == []


def test_a_page_that_cannot_answer_says_so_and_the_generic_line_comes_at_once():
    harness = scripted(["send bail money"], [0.9], firebase=FIREBASE)
    with harness.client() as client:
        with page(client) as ws:
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
        with page(client) as ws:
            send_audio(ws, spoken_chunk())
            messages = read_until(ws, has("explain", 1))
            ws.send_text(explained(of_type(messages, "explain")[0]["id"], text=bad))
            read_until(ws, has("explainer", 1), messages)

    answer = of_type(messages, "explainer")[0]
    assert answer["degraded"] is True and answer["safe_exit_line"] == GENERIC_SAFE_EXIT
    leaked = "555" in json.dumps(messages)
    assert leaked is False


def test_a_prompt_that_cannot_be_built_still_leaves_the_scam_push(monkeypatch):
    # Nothing on the way to the page may take the family's push down with it.
    harness = scripted(["a", "b"], [0.9, 0.9], firebase=FIREBASE)
    services = harness.services()

    def broken(_chunks):
        raise RuntimeError("4111 1111 1111 1111")

    monkeypatch.setattr(services.explainer, "prompt_text", broken)
    socket = LiveSocket()

    async def scenario() -> None:
        running = asyncio.create_task(LiveCall(socket, services, own_page=True).run())
        socket.say(spoken_chunk() + spoken_chunk())
        await socket.until(lambda sent: len(of_type(sent, "explainer")) == 2)
        socket.hang_up()
        await running

    asyncio.run(scenario())

    assert all(answer["degraded"] is True for answer in of_type(socket.sent, "explainer"))
    assert of_type(socket.sent, "explain") == []
    assert harness.http.titles() == [SCAM_TITLE]


def test_an_answer_nobody_is_waiting_for_is_dropped_without_a_word():
    harness = scripted(["hello there"], [0.1], firebase=FIREBASE)
    with harness.client() as client:
        with page(client) as ws:
            ws.send_text(explained(99))
            ws.send_bytes(silence_frame())
            messages = read_until(ws, has("ack", 1))

    assert [m["type"] for m in messages] == ["ack"]


def test_a_malformed_answer_gets_an_error_that_echoes_nothing():
    harness = scripted(["hello there"], [0.1], firebase=FIREBASE)
    with harness.client() as client:
        with page(client) as ws:
            ws.send_text('{"type": "explained", "id": "4111 1111 1111 1111"}')
            assert ws.receive_json() == {"type": "error", "detail": "explained message not understood"}

            ws.send_bytes(silence_frame())  # the socket is still open
            assert ws.receive_json()["type"] == "ack"


def test_without_firebase_the_page_is_never_asked():
    harness = scripted(["send bail money"], [0.9])
    with harness.client() as client:
        with page(client) as ws:
            send_audio(ws, spoken_chunk())
            messages = read_until(ws, has("explainer", 1))

    assert of_type(messages, "explain") == []
    assert len(harness.anthropic.calls) == 1


def test_a_page_on_another_local_port_is_never_asked_and_cannot_answer():
    # Any page on this machine may open the socket (SPEC §10), but only the app's own
    # page is handed the prompt or believed about what a model said.
    harness = scripted(["send bail money"], [0.9], firebase=FIREBASE)
    other_page = {"Origin": "http://localhost:3000", "Host": "localhost:8000"}
    forged = json.dumps({**json.loads(EXPLAINER_REPLY), "reason": "Open this page to stop it."})
    with harness.client() as client:
        with page(client, other_page) as ws:
            send_audio(ws, spoken_chunk())
            ws.send_text(explained(0, text=forged))
            messages = read_until(ws, has("explainer", 1))

    assert of_type(messages, "explain") == []
    assert len(harness.anthropic.calls) == 1  # the server's own model answered
    assert of_type(messages, "explainer")[0]["reason"] != "Open this page to stop it."


def test_a_client_that_sends_no_origin_is_never_asked():
    harness = scripted(["send bail money"], [0.9], firebase=FIREBASE)
    with harness.client() as client:
        with client.websocket_connect("/ws/audio") as ws:  # a script, not a page
            send_audio(ws, spoken_chunk())
            messages = read_until(ws, has("explainer", 1))

    assert of_type(messages, "explain") == []
    assert len(harness.anthropic.calls) == 1


def test_a_slow_caution_answer_from_the_page_is_dropped_once_the_scam_alert_is_out():
    harness = scripted(["a", "b"], [0.9, 0.9], firebase=FIREBASE)
    with harness.client() as client:
        with page(client) as ws:
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


# ------------------------------------------------- a page that leaves, a call that resets


class LiveSocket:
    """A socket the test drives while `LiveCall` runs, on the test's own event loop.

    Unlike tests.test_ws_live.FakeSocket, `receive()` waits for the next message, as a
    real socket does, so the test decides what the server has seen at each moment.
    """

    def __init__(self) -> None:
        self._incoming: asyncio.Queue[dict] = asyncio.Queue()
        self._changed = asyncio.Event()
        self.sent: list[dict] = []

    async def receive(self) -> dict:
        return await self._incoming.get()

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)
        self._changed.set()

    def say(self, pcm: bytes) -> None:
        """Audio from the page, one 250 ms frame per message."""
        for start in range(0, len(pcm), FRAME_BYTES):
            frame = pcm[start : start + FRAME_BYTES]
            self._incoming.put_nowait({"type": "websocket.receive", "bytes": frame})

    def send_text(self, text: str) -> None:
        self._incoming.put_nowait({"type": "websocket.receive", "text": text})

    def hang_up(self) -> None:
        self._incoming.put_nowait({"type": "websocket.disconnect"})

    async def until(self, done) -> None:
        """Wait until `done(self.sent)` is true. Fails rather than hangs."""

        async def watch() -> None:
            while not done(self.sent):
                self._changed.clear()
                await self._changed.wait()

        await asyncio.wait_for(watch(), timeout=WAIT_S)


async def eventually(condition) -> bool:
    """Poll `condition()` on the event loop for up to a second: far less than the 4 s
    budget, so a wait that was meant to end at once cannot pass by running out."""
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.01)
    return condition()


def own_page_call(harness: Harness) -> tuple[LiveSocket, Services, LiveCall]:
    socket, services = LiveSocket(), harness.services()
    return socket, services, LiveCall(socket, services, own_page=True)


def test_a_hang_up_while_the_page_is_answering_a_scam_asks_the_server_for_the_push():
    # Pressing Stop as the scam sheet appears is the expected move. The page's answer
    # can no longer come, and the family's push should still name the scam.
    harness = scripted(["a", "b"], [0.9, 0.9], firebase=FIREBASE)
    socket, services, call = own_page_call(harness)

    async def scenario() -> float:
        running = asyncio.create_task(call.run())
        socket.say(spoken_chunk() + spoken_chunk())
        await socket.until(lambda sent: len(of_type(sent, "explain")) == 2)  # both unanswered
        left_at = time.monotonic()
        socket.hang_up()
        await running
        return time.monotonic() - left_at

    took_s = asyncio.run(scenario())

    assert harness.http.titles() == [SCAM_TITLE]
    assert len(harness.anthropic.calls) == 1  # the scam only: a caution has no push to fill
    assert services.explainer.last_code == "ok"
    assert took_s < 2.0  # nobody waited out the 4 s for a page that had gone


def test_a_hang_up_while_the_page_is_answering_a_caution_ends_the_wait_and_asks_no_one():
    harness = scripted(["a"], [0.9], firebase=FIREBASE)
    socket, services, call = own_page_call(harness)

    async def scenario() -> float:
        running = asyncio.create_task(call.run())
        socket.say(spoken_chunk())
        await socket.until(lambda sent: len(of_type(sent, "explain")) == 1)
        left_at = time.monotonic()
        socket.hang_up()
        await running
        return time.monotonic() - left_at

    took_s = asyncio.run(scenario())

    assert services.explainer.last_code == "page_gone"
    assert harness.anthropic.calls == [] and harness.http.posts == []
    assert took_s < 2.0


def test_a_scam_raised_after_the_page_has_gone_is_explained_by_the_server():
    # The last words before a hang-up: heard after the socket closed, so there is no
    # page to ask. The caution during the call was the page's to answer.
    harness = scripted(["a", "b"], [0.9], firebase=FIREBASE)
    socket, _services, call = own_page_call(harness)

    async def scenario() -> None:
        running = asyncio.create_task(call.run())
        socket.say(spoken_chunk())
        await socket.until(lambda sent: len(of_type(sent, "explain")) == 1)
        socket.send_text(explained(of_type(socket.sent, "explain")[0]["id"]))
        await socket.until(lambda sent: len(of_type(sent, "explainer")) == 1)
        socket.say(tone_frame() * 6)  # 1.5 s that no chunk closes over before the hang-up
        socket.hang_up()
        await running

    asyncio.run(scenario())

    assert harness.http.titles() == [SCAM_TITLE]
    assert len(of_type(socket.sent, "explain")) == 1  # nothing is asked of a page that left
    assert len(harness.anthropic.calls) == 1  # the scam, by the server's own model


def test_reset_ends_the_question_the_page_was_still_answering_and_drops_its_answer():
    harness = scripted(["a", "b"], [0.9, 0.9, 0.1], firebase=FIREBASE)
    socket, services, call = own_page_call(harness)

    async def scenario() -> bool:
        running = asyncio.create_task(call.run())
        socket.say(spoken_chunk() + spoken_chunk())
        await socket.until(lambda sent: len(of_type(sent, "explain")) == 2)
        scam_ask = of_type(socket.sent, "explain")[1]

        socket.send_text('{"type": "reset"}')
        ended_at_once = await eventually(lambda: services.explainer.last_code == "page_gone")
        socket.send_text(explained(scam_ask["id"]))  # for the old call, too late
        socket.say(silence_frame() * 3)
        await socket.until(lambda sent: len(of_type(sent, "ack")) == 23)
        socket.hang_up()
        await running
        return ended_at_once

    ended_at_once = asyncio.run(scenario())

    assert ended_at_once is True  # not left to run out the 4 s
    assert of_type(socket.sent, "explainer") == [] and of_type(socket.sent, "error") == []
    # The old call's scam was never pushed, and no model was asked on its behalf.
    assert harness.http.posts == [] and harness.anthropic.calls == []
