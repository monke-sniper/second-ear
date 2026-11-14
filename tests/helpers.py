"""Test doubles and PCM helpers. Imported by tests, never by the app."""

from __future__ import annotations

from typing import Sequence

from server.contracts import FRAME_BYTES, TranscriptChunk


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


def silence_frame() -> bytes:
    """One 250 ms frame of 16 kHz mono s16le silence."""
    return b"\x00\x00" * (FRAME_BYTES // 2)


def tone_frame(value: int = 1000) -> bytes:
    """One 250 ms frame of constant s16le amplitude, for chunker tests."""
    import struct

    return struct.pack("<h", value) * (FRAME_BYTES // 2)


def chunk(text: str, end_s: float, duration_s: float = 4.0) -> TranscriptChunk:
    """A transcript chunk ending at `end_s`, with no language label."""
    return TranscriptChunk(text=text, start_s=max(0.0, end_s - duration_s), end_s=end_s)
