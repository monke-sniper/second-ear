"""Speech to text, one audio chunk at a time.

In: one 2–6 s chunk of 16 kHz mono s16le PCM.
Out: English text with its time window inside the call, from faster-whisper on the GPU.
It does not score, classify, store audio, or write transcripts to disk.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from server.contracts import SAMPLE_RATE, SAMPLE_WIDTH_BYTES, TranscriptChunk


@dataclass(frozen=True)
class SttConfig:
    """Whisper settings for the live call. Mirrors .env, overridable per instance."""

    model_size: str = "base.en"
    device: str = "cuda"
    compute_type: str = "float16"
    language: str | None = None  # None = auto-detect; output is always English
    task: str = "translate"  # non-English speech still lands in English
    vad_filter: bool = True  # silence must not become invented words
    beam_size: int = 1


def pcm16_to_float32(pcm: bytes) -> np.ndarray:
    """Convert signed 16-bit little-endian PCM bytes to float32 in [-1, 1]."""
    if len(pcm) % SAMPLE_WIDTH_BYTES:
        raise ValueError("PCM length must be a multiple of 2 bytes (s16le)")
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


class StreamTranscriber:
    """Holds the Whisper model for one process and transcribes chunk by chunk.

    The model is loaded lazily so importing this module stays cheap, and `warmup()`
    exists because the first CUDA call pays the context-init cost — pay it before
    the demo, never during it. Call `reset()` when a new call starts so Whisper's
    rolling prompt cannot leak one call's words into the next.
    """

    def __init__(self, config: SttConfig | None = None) -> None:
        self.config = config or SttConfig()
        self._model = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def warmup(self) -> None:
        """Load the model and transcribe one second of silence to force GPU init."""
        raise NotImplementedError("stt lands in phase 3 — docs/SPEC.md §4")

    def transcribe(self, pcm: bytes, *, start_s: float = 0.0) -> TranscriptChunk:
        """Transcribe one chunk.

        `start_s` is the chunk's offset in the call; the returned `end_s` is
        `start_s + len(pcm) / 32_000` because the audio is 16 kHz s16le.
        Empty speech returns an empty `text`, never "thank you" — `vad_filter` is on.
        """
        raise NotImplementedError("stt lands in phase 3 — docs/SPEC.md §4")

    def reset(self) -> None:
        """Forget the previous call's decoding state. The model stays loaded."""
        raise NotImplementedError("stt lands in phase 3 — docs/SPEC.md §4")


def pcm_duration_s(pcm: bytes) -> float:
    """Seconds of audio in a PCM buffer at the contracted sample rate."""
    return len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH_BYTES)
