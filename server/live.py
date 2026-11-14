"""One live call over the audio socket: PCM frames in, events out.

In: the browser's binary frames and its `reset` message.
Out: an ack per frame, then transcript, risk, alert and danger events, then the
explainer's late answer. It owns the connection's send lock and background tasks.
It does not hold any rule: those live in pipeline.py and the modules it calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Protocol, Sequence

from fastapi import WebSocket, WebSocketDisconnect

from server.chunker import AudioChunker, is_silent
from server.contracts import (
    MAX_FRAME_BYTES,
    AlertEvent,
    AlertLevel,
    AudioAck,
    ErrorEvent,
    TranscriptChunk,
    WireModel,
)
from server.explainer import Explainer
from server.notify import NtfyNotifier
from server.pipeline import CallSession, Step, explainer_event
from server.scorer import RiskScorer
from server.stt import pcm_duration_s

log = logging.getLogger("second_ear.live")

RESET = "reset"
UNKNOWN_EVENT = "unknown"
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
    """The long-lived parts every connection shares. A notifier is made per call."""

    transcriber: Transcriber
    scorer: RiskScorer
    explainer: Explainer
    notifier_factory: Callable[[], NtfyNotifier]


def event_type(text: str) -> str:
    """The `type` of a client text message, or `unknown` if it is not a plain name."""
    try:
        payload = json.loads(text)
    except ValueError:
        return UNKNOWN_EVENT
    kind = payload.get("type") if isinstance(payload, dict) else None
    if isinstance(kind, str) and _EVENT_NAME.fullmatch(kind):
        return kind
    return UNKNOWN_EVENT


class LiveCall:
    """Runs one socket from accept to close.

    Frames are handled in order, one chunk at a time: Whisper and the scorer run in a
    worker thread, and the alert is sent the moment the rules raise it. The explainer
    and the pushes run as background tasks so the next chunk is never held up. A
    `reset` starts a new call; an explainer answer that arrives after it is dropped,
    with the push that would have followed.
    """

    def __init__(self, ws: WebSocket, services: Services) -> None:
        self.ws = ws
        self.services = services
        self.session = CallSession(services.scorer)
        self.chunker = AudioChunker()
        self.notifier = services.notifier_factory()
        self.total = 0
        self._send_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self._open = True

    async def run(self) -> None:
        """Serve the socket until the client leaves, then let open tasks finish."""
        try:
            while True:
                message = await self.ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                data = message.get("bytes")
                if data is not None:
                    await self._on_audio(data)
                else:
                    await self._on_text(message.get("text") or "")
        except WebSocketDisconnect:
            pass
        finally:
            self._open = False
            log.info("audio socket closed after %d bytes", self.total)
            # A hang-up is not a reset: a scam push already on its way still goes out.
            # `wait`, not `gather`: if this handler is cancelled, the tasks are not.
            if self._tasks:
                await asyncio.wait(self._tasks)

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

    def _reset(self) -> None:
        """A new call on the same socket. The old call's notifier is left behind."""
        self.session.reset()
        self.chunker.reset()
        self.notifier = self.services.notifier_factory()
        self.total = 0

    async def _on_chunk(self, pcm: bytes) -> None:
        try:
            step = await asyncio.to_thread(self._hear, pcm)
        except Exception as exc:
            log.warning("chunk failed: %s", type(exc).__name__)
            await self._send(ErrorEvent(detail="could not process that audio"))
            return
        for event in step.events:
            await self._send(event)
        if step.alert is not None:
            self._spawn(
                self._enrich(step.alert, self.session.chunks, self.session.generation, self.notifier)
            )
        if step.danger is not None:
            self._spawn(self._push_code(self.notifier))

    def _hear(self, pcm: bytes) -> Step:
        """Worker thread: transcribe unless the chunk is all quiet, then run the rules.

        A chunk Whisper cannot read is treated as silence: the clock still moves.
        """
        text = ""
        if not is_silent(pcm, self.chunker.config.pause_db):
            try:
                text = self.services.transcriber.transcribe(pcm, start_s=self.session.now_s).text
            except Exception as exc:
                log.warning("transcribe failed: %s", type(exc).__name__)
        return self.session.ingest(text, pcm_duration_s(pcm))

    async def _enrich(
        self,
        alert: AlertEvent,
        chunks: Sequence[TranscriptChunk],
        generation: int,
        notifier: NtfyNotifier,
    ) -> None:
        """After the alert is out: name the scam, then tell the family if it is one."""
        explain = self.services.explainer.explain
        try:
            result = await asyncio.to_thread(explain, chunks, alert.score)
            if generation != self.session.generation:
                return  # a reset started a new call; this answer belongs to the old one
            await self._send(explainer_event(result, alert.t_s))
            if alert.level is AlertLevel.scam:
                await asyncio.to_thread(notifier.send_scam, result)
        except Exception as exc:  # the alert is already on screen and must stay there
            log.warning("explainer task failed: %s", type(exc).__name__)

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
