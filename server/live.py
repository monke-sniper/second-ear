"""One live call over the audio socket: PCM frames in, events out.

In: the browser's binary frames, its `reset` message, and its `explained` answers.
Out: an ack per frame, then transcript, risk, alert and danger events, then the
explainer's late answer. It owns the connection's send lock and background tasks.
It does not hold any rule: those live in pipeline.py and the modules it calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from dataclasses import dataclass, replace
from typing import Any, Callable, Coroutine, Protocol, Sequence

from fastapi import WebSocket, WebSocketDisconnect

from server.chunker import AudioChunker, is_silent
from server.contracts import (
    MAX_FRAME_BYTES,
    AlertEvent,
    AlertLevel,
    AudioAck,
    ErrorEvent,
    ExplainerResult,
    ExplainRequest,
    TranscriptChunk,
    WireModel,
)
from server.explainer import Explainer
from server.notify import NtfyNotifier
from server.page_explainer import (
    PAGE_GONE,
    PAGE_NO_ANSWER,
    PAGE_TIMEOUT,
    PageDesk,
    parse_explained,
)
from server.pipeline import CallSession, Step, explainer_event
from server.scorer import RiskScorer
from server.stt import pcm_duration_s

log = logging.getLogger("second_ear.live")

RESET = "reset"
EXPLAINED = "explained"
UNKNOWN_EVENT = "unknown"
# What the client is told, once per call, when a chunk could not be read.
UNREAD_DETAIL = "could not process that audio"
# What the page is told when its `explained` message is not the shape in contracts.py.
EXPLAINED_DETAIL = "explained message not understood"
# The `source` of an answer from a page that could not ask a model.
NO_SOURCE = "none"
# How many messages the reader may hold ahead of Whisper: about a minute of audio at
# four frames a second. Past that it stops reading and the socket's own buffer fills.
INBOX_MESSAGES = 256
# One message as the ASGI server hands it over.
Message = dict[str, Any]
# docs/SPEC.md §2. Mid-call a chunk waits for 2 s and a pause. When the call ends no
# more audio is coming, so what is left is heard from half a second up.
END_TAIL_MIN_S = 0.5
# Only a plain lowercase name is echoed back; client text is never copied into a reply.
_EVENT_NAME = re.compile(r"[a-z_]{1,32}")
# Background tasks of every connection, held until each one is done.
_IN_FLIGHT: set[asyncio.Task[None]] = set()


class Transcriber(Protocol):
    """What the socket needs from speech-to-text. Tests pass a fake."""

    def warmup(self) -> None: ...

    def transcribe(self, pcm: bytes, *, start_s: float = 0.0) -> TranscriptChunk: ...


@dataclass(frozen=True)
class Services:
    """The long-lived parts every connection shares. A notifier is made per call.

    `ask_page` is true when Firebase is set up: the page then makes the explainer's
    model call (Firebase AI Logic) while it is connected, and `explainer` checks it.
    """

    transcriber: Transcriber
    scorer: RiskScorer
    explainer: Explainer
    notifier_factory: Callable[[], NtfyNotifier]
    ask_page: bool = False


def event_type(text: str) -> str:
    """The `type` of a client text message, or `unknown` if it is not a plain name."""
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError):  # not JSON, or nested too deep to read
        return UNKNOWN_EVENT
    kind = payload.get("type") if isinstance(payload, dict) else None
    if isinstance(kind, str) and _EVENT_NAME.fullmatch(kind):
        return kind
    return UNKNOWN_EVENT


class LiveCall:
    """Runs one socket from accept to close.

    Frames are handled in order, one chunk at a time: Whisper and the scorer run in a
    worker thread, and the alert is sent the moment the rules raise it. The explainer
    and the pushes run as background tasks so the next chunk is never held up. The
    page's `explained` answer is the one message taken out of order, as it arrives. A
    `reset` starts a new call; an explainer answer that arrives after it is dropped,
    with the push that would have followed. So is an answer for an alert that a higher
    alert has replaced. When the client leaves, the audio no chunk had closed over is
    still heard, so the last words of a call can still raise an alert or a push.
    """

    def __init__(self, ws: WebSocket, services: Services, *, own_page: bool = False) -> None:
        self.ws = ws
        self.services = services
        self.session = CallSession(services.scorer)
        self.chunker = AudioChunker()
        self.notifier = services.notifier_factory()
        self.page = PageDesk()
        self.total = 0
        # Only the page this server served is handed the prompt and believed about what
        # a model said (`own_page`, app.is_own_page).
        self._asks_page = services.ask_page and own_page
        self._send_lock = asyncio.Lock()
        self._hearing = threading.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        # `_open` goes false when the hang-up is reached in order, after the audio sent
        # before it; `_gone` the moment the socket closes, which can be much earlier.
        self._open = True
        self._gone = False
        self._unread_said = False

    async def run(self) -> None:
        """Serve the socket until the client leaves, then let open tasks finish."""
        inbox: asyncio.Queue[Message | None] = asyncio.Queue(maxsize=INBOX_MESSAGES)
        reader = asyncio.create_task(self._read(inbox))
        try:
            while (message := await inbox.get()) is not None:
                data = message.get("bytes")
                if data is not None:
                    await self._on_audio(data)
                else:
                    await self._on_text(message.get("text") or "")
        finally:
            reader.cancel()
            self._open = False
            self._page_left()
            log.info("audio socket closed after %d bytes", self.total)
            # A hang-up is not a reset: the last words are still heard, and a push on
            # its way still goes out. The tail is a task of its own, started before
            # anything is awaited, so it outlives a handler that is cancelled while it
            # waits for a frame (the test client does that; uvicorn does not cancel).
            # A handler cancelled while a chunk is in Whisper loses that chunk's alert.
            self._spawn(self._hear_tail())
            # `wait`, not `gather`: if this handler is cancelled, the tasks are not.
            # In a loop, because the tail can start an explainer and a push of its own.
            while self._tasks:
                await asyncio.wait(self._tasks)

    async def _read(self, inbox: asyncio.Queue[Message | None]) -> None:
        """Take messages off the socket as they arrive, and queue them for `run`.

        Audio and `reset` are handled in order, one at a time, and a chunk in Whisper
        holds up everything behind it. The page's `explained` answer must not wait in
        that line: its budget is running. So it is handed over here, the moment it
        comes. `None` in the queue is the hang-up, placed after the audio before it.
        """
        try:
            while True:
                message = await self.ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                text = message.get("text")
                if text is not None and message.get("bytes") is None and event_type(text) == EXPLAINED:
                    await self._on_explained(text)
                else:
                    await inbox.put(message)  # waits when the queue is full
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            log.warning("socket reader failed: %s", type(exc).__name__)
        self._page_left()
        await inbox.put(None)

    def _page_left(self) -> None:
        """The socket has closed: nothing the page was asked can come back."""
        self._gone = True
        self.page.abandon()

    async def _on_audio(self, data: bytes) -> None:
        if len(data) > MAX_FRAME_BYTES:
            await self._send(ErrorEvent(detail="audio frame too large"))
            return
        self.total += len(data)
        await self._send(AudioAck(bytes=len(data), total=self.total))
        for chunk in self.chunker.feed(data):
            await self._on_chunk(chunk)

    async def _on_text(self, text: str) -> None:
        kind = event_type(text)
        if kind == RESET:
            self._reset()
            return
        await self._send(ErrorEvent(detail=f"event not handled: {kind}"))

    async def _on_explained(self, text: str) -> None:
        """The page's answer to an `explain` request, taken as it arrives."""
        answer = parse_explained(text)
        if answer is None:
            await self._send(ErrorEvent(detail=EXPLAINED_DETAIL))
            return
        # An answer nobody is waiting for (late, for an id never asked, or from a page
        # that is never asked) is dropped.
        self.page.settle(answer)

    def _reset(self) -> None:
        """A new call on the same socket. The old call's notifier is left behind, and
        so is whatever the page was still being asked about it."""
        self.session.reset()
        self.chunker.reset()
        self.page.abandon()
        self.notifier = self.services.notifier_factory()
        self.total = 0
        self._unread_said = False

    async def _on_chunk(self, pcm: bytes) -> None:
        try:
            step, unread = await asyncio.to_thread(self._hear, pcm)
        except Exception as exc:
            log.warning("chunk failed: %s", type(exc).__name__)
            await self._say_unread()
            return
        if unread:
            await self._say_unread()
        for event in step.events:
            await self._send(event)
        alert = step.alert
        # Once the client has gone an answer has nowhere to go, so the explainer is
        # asked only when a push will use what it says.
        if alert is not None and (self._open or alert.level is AlertLevel.scam):
            self._spawn(
                self._enrich(alert, self.session.chunks, self.session.generation, self.notifier)
            )
        if step.danger is not None:
            self._spawn(self._push_code(self.notifier))

    def _hear(self, pcm: bytes) -> tuple[Step, bool]:
        """Worker thread: transcribe unless the chunk is all quiet, then run the rules.

        Returns the chunk's step, and True when Whisper failed on it. Such a chunk is
        treated as silence, so the clock still moves, but it must not pass for a quiet
        call: the caller tells the client.
        """
        # One chunk at a time, even when a cancelled handler left a thread running.
        with self._hearing:
            text, unread = "", False
            if not is_silent(pcm, self.chunker.config.pause_db):
                try:
                    heard = self.services.transcriber.transcribe(pcm, start_s=self.session.now_s)
                    text = heard.text
                except Exception as exc:
                    log.warning("transcribe failed: %s", type(exc).__name__)
                    unread = True
            return self.session.ingest(text, pcm_duration_s(pcm)), unread

    async def _say_unread(self) -> None:
        """Tell the client, once per call, that some audio could not be read."""
        if self._unread_said:
            return
        self._unread_said = True
        await self._send(ErrorEvent(detail=UNREAD_DETAIL))

    async def _hear_tail(self) -> None:
        """End of call: hear the audio that no chunk had closed over yet.

        It goes down the same path as any chunk, so it can raise an alert, the code
        warning and their pushes. A quiet tail stops in `_hear`, like a quiet chunk.
        Nothing is sent: the socket is closed, and `_send` knows it.
        """
        # `flush()` returns a tail of at least `min_s`; the call is over, so lower it.
        self.chunker.config = replace(self.chunker.config, min_s=END_TAIL_MIN_S)
        tail = self.chunker.flush()
        if tail is not None:
            await self._on_chunk(tail)

    async def _enrich(
        self,
        alert: AlertEvent,
        chunks: Sequence[TranscriptChunk],
        generation: int,
        notifier: NtfyNotifier,
    ) -> None:
        """After the alert is out: name the scam, then tell the family if it is one."""
        try:
            result = await self._explain(alert, chunks, generation)
            if generation != self.session.generation:
                return  # a reset started a new call; this answer belongs to the old one
            if self.session.outranked(alert.level):
                return  # a higher alert went out meanwhile; its own answer is the one to show
            # Nothing is awaited between that check and the send lock, and the lock is
            # first come, first served: an answer that passes goes out before the next
            # alert can.
            await self._send(explainer_event(result, alert.t_s))
            if alert.level is AlertLevel.scam:
                await asyncio.to_thread(notifier.send_scam, result)
        except Exception as exc:  # the alert is already on screen and must stay there
            log.warning("explainer task failed: %s", type(exc).__name__)

    async def _explain(
        self, alert: AlertEvent, chunks: Sequence[TranscriptChunk], generation: int
    ) -> ExplainerResult:
        """The explainer's read of the call: from the page's model while Firebase is set
        up and the app's own page is there to ask, from the server's own model otherwise.

        A page that leaves before it answers a scam alert hands the question to the
        server's model, because the family's push is still to come. A caution has no
        push, and a reset call has no use for an answer: those get the generic line.
        """
        explainer = self.services.explainer
        if not (self._asks_page and self._open and not self._gone):
            return await asyncio.to_thread(explainer.explain, chunks, alert.score)
        try:
            result = await self._ask_page(alert, chunks)
        except Exception as exc:  # whatever went wrong, the scam push still has to go
            return explainer.degraded(f"error:{type(exc).__name__}")
        if result is not None:
            return result
        same_call = generation == self.session.generation
        if same_call and alert.level is AlertLevel.scam:
            return await asyncio.to_thread(explainer.explain, chunks, alert.score)
        return explainer.degraded(PAGE_GONE)

    async def _ask_page(
        self, alert: AlertEvent, chunks: Sequence[TranscriptChunk]
    ) -> ExplainerResult | None:
        """Send the page the redacted prompt and wait, inside the budget, for its answer.

        The page asks Gemini Nano on the device, or cloud Gemini when Chrome has none
        (Firebase AI Logic hybrid inference). What it sends back is checked like any
        other reply; no answer in time is the generic line. The alert never waits.
        Returns None when the page left, or the call was reset, before it answered.
        """
        explainer = self.services.explainer
        prompt = explainer.prompt_text(chunks)
        if prompt is None:
            return explainer.degraded("empty_transcript")
        request_id, waiting = self.page.expect()
        try:
            await self._send(ExplainRequest(id=request_id, t_s=alert.t_s, prompt=prompt))
            if self._gone or not self._open:  # it left as the request went out
                return None
            answer = await asyncio.wait_for(waiting, timeout=explainer.timeout_s)
        except asyncio.TimeoutError:
            return explainer.degraded(PAGE_TIMEOUT)
        finally:
            self.page.close(request_id)
        if answer is None:
            return None
        if answer.source == NO_SOURCE:
            return explainer.degraded(PAGE_NO_ANSWER)
        # Where the model ran is one of two fixed words, so it is safe in a log line.
        log.info("explainer answered by the page: %s", answer.source)
        return explainer.from_reply(answer.text)

    async def _push_code(self, notifier: NtfyNotifier) -> None:
        try:
            await asyncio.to_thread(notifier.send_code)
        except Exception as exc:
            log.warning("code push task failed: %s", type(exc).__name__)

    def _spawn(self, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(work)
        # The loop keeps only weak references; these two sets keep the task alive,
        # the second one even after this connection is gone.
        for holder in (self._tasks, _IN_FLIGHT):
            holder.add(task)
            task.add_done_callback(holder.discard)

    async def _send(self, event: WireModel) -> None:
        """Send one event. The lock keeps a background answer from splitting another
        send; a client that has gone is noted, never raised."""
        async with self._send_lock:
            if not self._open:
                return
            try:
                await self.ws.send_json(event.model_dump(mode="json"))
            except (WebSocketDisconnect, RuntimeError):
                self._open = False
