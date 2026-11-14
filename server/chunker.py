"""Turns the raw mic stream into speech-sized chunks.

In: 16 kHz mono s16le PCM frames, 250 ms each, arriving from the browser.
Out: whole chunks cut at pauses, 2–6 s long, never mid-word.
It does not transcribe, score, or decide anything; it only decides where a chunk ends.
"""

from __future__ import annotations

from dataclasses import dataclass

from server.contracts import FRAME_BYTES, SAMPLE_RATE, SAMPLE_WIDTH_BYTES


@dataclass(frozen=True)
class ChunkerConfig:
    """Where a chunk may start and end. Values are frozen by docs/SPEC.md §2."""

    min_s: float = 2.0
    max_s: float = 6.0
    pause_db: float = -38.0
    pause_frames: int = 2

    @property
    def bytes_per_second(self) -> int:
        return SAMPLE_RATE * SAMPLE_WIDTH_BYTES


class AudioChunker:
    """Per-call audio buffer. One instance per WebSocket connection.

    `feed()` is called with every frame the socket receives and returns the chunks
    that are complete after that frame. A chunk closes when a pause of at least
    `pause_frames` × 250 ms is detected after `min_s`, or at `max_s` regardless.
    Silence shorter than the pause threshold stays inside the chunk, so a word
    split across two frames is never split across two chunks.
    """

    def __init__(self, config: ChunkerConfig | None = None) -> None:
        self.config = config or ChunkerConfig()
        self._buffer = bytearray()
        self._silent_run = 0
        self._frames_seen = 0

    def feed(self, pcm: bytes) -> list[bytes]:
        """Append one frame (or several) and return every chunk that is now complete.

        A returned chunk is always between `min_s` and `max_s` seconds long.
        Never returns the same audio twice; frames are consumed as they arrive.
        """
        raise NotImplementedError("chunker lands in phase 3 — docs/SPEC.md §4")

    def flush(self) -> bytes | None:
        """End of call: return the unclosed tail if it is at least `min_s`, else None."""
        raise NotImplementedError("chunker lands in phase 3 — docs/SPEC.md §4")

    def reset(self) -> None:
        """Drop all buffered audio and pause state. Called on `{"type": "reset"}`."""
        self._buffer.clear()
        self._silent_run = 0
        self._frames_seen = 0

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    @property
    def buffered_s(self) -> float:
        return len(self._buffer) / (SAMPLE_RATE * SAMPLE_WIDTH_BYTES)

    @property
    def frame_bytes(self) -> int:
        return FRAME_BYTES
