"""Turns the raw mic stream into speech-sized chunks.

In: 16 kHz mono s16le PCM frames, 250 ms each, arriving from the browser.
Out: whole chunks cut at pauses, 2–6 s long, never mid-word.
It does not transcribe, score, or decide anything; it only decides where a chunk ends.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from server.contracts import FRAME_BYTES, FRAME_MS, SAMPLE_RATE, SAMPLE_WIDTH_BYTES

FRAME_S = FRAME_MS / 1000
# What an all-zero frame measures as, instead of minus infinity.
SILENCE_FLOOR_DB = -120.0
INT16_FULL_SCALE = 32768.0


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


def frame_db(pcm: bytes) -> float:
    """Loudness of a PCM buffer in dBFS (RMS). Silence returns `SILENCE_FLOOR_DB`."""
    usable = len(pcm) - len(pcm) % SAMPLE_WIDTH_BYTES
    if usable == 0:
        return SILENCE_FLOOR_DB
    samples = np.frombuffer(pcm[:usable], dtype="<i2").astype(np.float64) / INT16_FULL_SCALE
    rms = math.sqrt(float(np.mean(samples * samples)))
    if rms <= 0.0:
        return SILENCE_FLOOR_DB
    return max(SILENCE_FLOOR_DB, 20.0 * math.log10(rms))


def is_silent(pcm: bytes, pause_db: float = ChunkerConfig.pause_db) -> bool:
    """True when every 250 ms frame of `pcm` is quieter than `pause_db`.

    The app uses it to skip Whisper on a chunk that holds no speech at all. One loud
    frame anywhere makes the chunk not silent.
    """
    frames = (pcm[start : start + FRAME_BYTES] for start in range(0, len(pcm), FRAME_BYTES))
    return all(frame_db(frame) < pause_db for frame in frames)


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
        Input of any size is re-framed: bytes wait in the buffer until a whole
        250 ms frame exists, so how the socket slices the stream changes nothing.
        """
        self._buffer.extend(pcm)
        chunks: list[bytes] = []
        while len(self._buffer) - self._analysed_bytes >= FRAME_BYTES:
            start = self._analysed_bytes
            frame = bytes(self._buffer[start : start + FRAME_BYTES])
            quiet = frame_db(frame) < self.config.pause_db
            self._silent_run = self._silent_run + 1 if quiet else 0
            self._frames_seen += 1
            if self._should_close():
                chunks.append(self._take(self._analysed_bytes))
        return chunks

    def flush(self) -> bytes | None:
        """End of call: return the unclosed tail if it is at least `min_s`, else None.

        The buffer is emptied either way. A trailing half sample is dropped.
        """
        usable = len(self._buffer) - len(self._buffer) % SAMPLE_WIDTH_BYTES
        tail = bytes(self._buffer[:usable])
        self.reset()
        if len(tail) < self.config.min_s * self.config.bytes_per_second:
            return None
        return tail

    @property
    def _analysed_bytes(self) -> int:
        return self._frames_seen * FRAME_BYTES

    def _should_close(self) -> bool:
        chunk_s = self._frames_seen * FRAME_S
        at_pause = chunk_s >= self.config.min_s and self._silent_run >= self.config.pause_frames
        return at_pause or chunk_s >= self.config.max_s

    def _take(self, size: int) -> bytes:
        """Remove and return the first `size` bytes; the next chunk starts clean."""
        chunk = bytes(self._buffer[:size])
        del self._buffer[:size]
        self._silent_run = 0
        self._frames_seen = 0
        return chunk

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
