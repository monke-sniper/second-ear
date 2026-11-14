"""Test doubles and PCM helpers. Imported by tests, never by the app."""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from typing import Callable, Sequence

from server.contracts import FRAME_BYTES, TranscriptChunk
from server.explainer import Org
from server.stt import pcm_duration_s


class ScriptedScorer:
    """Returns scores in order, then repeats the last one. Stands in for DistilBERT."""

    name = "scripted"

    def __init__(self, scores: Sequence[float]) -> None:
        if not scores:
            raise ValueError("ScriptedScorer needs at least one score")
        self._scores = [float(s) for s in scores]
        self._index = 0
        self.calls: list[str] = []

    def score(self, transcript: str) -> float:
        self.calls.append(transcript)
        value = self._scores[min(self._index, len(self._scores) - 1)]
        self._index += 1
        return value


class FakeTranscriber:
    """Returns texts in order, then repeats the last one. Stands in for Whisper."""

    def __init__(self, texts: Sequence[str] = ("hello",), raises: Exception | None = None) -> None:
        self._texts = list(texts)
        self.raises = raises
        self.calls: list[int] = []
        self.warmed = threading.Event()

    def warmup(self) -> None:
        self.warmed.set()
        if self.raises is not None:
            raise self.raises

    def transcribe(self, pcm: bytes, *, start_s: float = 0.0) -> TranscriptChunk:
        index = len(self.calls)
        self.calls.append(len(pcm))
        if self.raises is not None:
            raise self.raises
        text = self._texts[min(index, len(self._texts) - 1)]
        return TranscriptChunk(text=text, start_s=start_s, end_s=start_s + pcm_duration_s(pcm))

    def reset(self) -> None:
        return None


EXPLAINER_REPLY = json.dumps(
    {
        "scam_type": "grandparent",
        "reason": "Caller claims to be a grandchild who needs money in secret.",
        "safe_exit_line": "I will hang up and call my grandson myself.",
        "claimed_org": None,
    }
)

FAKE_ORGS = {"chase": Org(id="chase", name="Chase", phone=None, aliases=("chase",))}


class FakeAnthropic:
    """Same surface as `anthropic.Anthropic.messages.create`; no network, no key.

    `gate`, when given, holds every request until the test sets it, which is how a
    test makes a reply arrive late. `done` is set each time a request finishes.
    """

    def __init__(
        self,
        text: str = EXPLAINER_REPLY,
        raises: BaseException | None = None,
        gate: threading.Event | None = None,
    ) -> None:
        self.text = text
        self.raises = raises
        self.gate = gate
        self.calls: list[dict] = []
        self.done = threading.Event()
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        try:
            if self.gate is not None:
                self.gate.wait(timeout=3.0)
            if self.raises is not None:
                raise self.raises
            return SimpleNamespace(content=[SimpleNamespace(text=self.text)])
        finally:
            self.done.set()


class FakeHttp:
    """Same surface as `httpx.Client.post`; records what a push would have sent."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.posts: list[tuple[str, dict]] = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return SimpleNamespace(status_code=self.status_code, text="ok")

    def titles(self) -> list[str]:
        return [kwargs["json"]["title"] for _url, kwargs in self.posts]


def wait_for(condition: Callable[[], bool], timeout_s: float = 3.0) -> bool:
    """Poll until `condition()` is true or the time is up. Returns the last answer."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def silence_frame() -> bytes:
    """One 250 ms frame of 16 kHz mono s16le silence."""
    return b"\x00\x00" * (FRAME_BYTES // 2)


def tone_frame(value: int = 1000) -> bytes:
    """One 250 ms frame of constant s16le amplitude, for chunker tests."""
    import struct

    return struct.pack("<h", value) * (FRAME_BYTES // 2)


def spoken_chunk(loud_frames: int = 8, quiet_frames: int = 2) -> bytes:
    """Audio the chunker cuts as one chunk: 2 s of tone, then a 500 ms pause."""
    return tone_frame() * loud_frames + silence_frame() * quiet_frames


def send_audio(ws, pcm: bytes) -> None:
    """Send PCM the way the browser does: one 250 ms frame per message."""
    for start in range(0, len(pcm), FRAME_BYTES):
        ws.send_bytes(pcm[start : start + FRAME_BYTES])


def chunk(text: str, end_s: float, duration_s: float = 4.0) -> TranscriptChunk:
    """A transcript chunk ending at `end_s`, with no language label."""
    return TranscriptChunk(text=text, start_s=max(0.0, end_s - duration_s), end_s=end_s)
