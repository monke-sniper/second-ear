"""Speech to text, one audio chunk at a time.

In: one 2–6 s chunk of 16 kHz mono s16le PCM.
Out: English text with its time window inside the call, from faster-whisper on the GPU.
It does not score, classify, store audio, or write transcripts to disk.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from server.config import get_settings
from server.contracts import SAMPLE_RATE, SAMPLE_WIDTH_BYTES, TranscriptChunk

log = logging.getLogger("second_ear.stt")

# Where Whisper goes when CUDA will not load or will not decode.
FALLBACK_DEVICE = "cpu"
FALLBACK_COMPUTE_TYPE = "int8"
# English-only checkpoints ("base.en", "small.en") cannot translate.
ENGLISH_ONLY_SUFFIX = ".en"

# (model_size, device, compute_type) -> an object with faster-whisper's `transcribe`.
ModelFactory = Callable[[str, str, str], Any]


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


def decode_options(config: SttConfig) -> dict[str, Any]:
    """The keyword arguments every `transcribe` call uses.

    An `.en` model is English-only: it gets `language="en", task="transcribe"`. Any
    other model keeps the configured language and translates into English. Chunks are
    always decoded on their own (`condition_on_previous_text=False`), so one chunk's
    mistake cannot be repeated into the next and one call cannot leak into another.
    """
    english_only = config.model_size.endswith(ENGLISH_ONLY_SUFFIX)
    return {
        "language": "en" if english_only else config.language,
        "task": "transcribe" if english_only else config.task,
        "vad_filter": config.vad_filter,
        "beam_size": config.beam_size,
        "condition_on_previous_text": False,
    }


def pcm16_to_float32(pcm: bytes) -> np.ndarray:
    """Convert signed 16-bit little-endian PCM bytes to float32 in [-1, 1]."""
    if len(pcm) % SAMPLE_WIDTH_BYTES:
        raise ValueError("PCM length must be a multiple of 2 bytes (s16le)")
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def _whisper_model(model_size: str, device: str, compute_type: str) -> Any:
    from faster_whisper import WhisperModel  # heavy import, paid on first load only

    return WhisperModel(model_size, device=device, compute_type=compute_type)


class StreamTranscriber:
    """Holds the Whisper model for one process and transcribes chunk by chunk.

    The model is loaded lazily so importing this module stays cheap, and `warmup()`
    exists because the first CUDA call pays the context-init cost — pay it before
    the demo, never during it. If CUDA fails, at load or on a decode, the model is
    reloaded on cpu/int8 and stays there. One instance serves every connection:
    nothing is remembered between chunks, so there is nothing to mix up.
    `model_factory` lets tests pass a fake in place of faster-whisper.
    """

    def __init__(
        self, config: SttConfig | None = None, model_factory: ModelFactory | None = None
    ) -> None:
        self.config = config or SttConfig()
        self._factory = model_factory or _whisper_model
        self._lock = threading.Lock()
        self._model: Any = None
        self.device: str | None = None  # where the model actually loaded

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def warmup(self) -> None:
        """Load the model and decode one second of silence to force GPU init.

        The VAD is off for this one call. With it on, silence is dropped before the
        model runs, the GPU is never touched, and a missing CUDA library would only
        show up on the first real word of a call. This way the fallback to the CPU
        happens here, at startup. Whatever Whisper invents for silence is discarded.
        """
        self._decode(np.zeros(SAMPLE_RATE, dtype=np.float32), vad_filter=False)

    def transcribe(self, pcm: bytes, *, start_s: float = 0.0) -> TranscriptChunk:
        """Transcribe one chunk.

        `start_s` is the chunk's offset in the call; the returned `end_s` is
        `start_s + len(pcm) / 32_000` because the audio is 16 kHz s16le.
        Empty speech returns an empty `text`, never "thank you" — `vad_filter` is on.
        """
        text, language = self._decode(pcm16_to_float32(pcm))
        return TranscriptChunk(
            text=text, start_s=start_s, end_s=start_s + pcm_duration_s(pcm), language=language
        )

    def reset(self) -> None:
        """Nothing to forget: each chunk is decoded on its own. The model stays loaded."""
        return None

    def _decode(self, audio: np.ndarray, **overrides: Any) -> tuple[str, str | None]:
        """Run Whisper, and once on the CPU if the configured device fails."""
        options = {**decode_options(self.config), **overrides}
        model = self._ensure_model()
        try:
            return self._run(model, audio, options)
        except Exception as exc:
            if self.device == FALLBACK_DEVICE:
                raise
            # CUDA can load and still fail on the first real decode (a missing DLL).
            log.warning("whisper decode on %s failed: %s", self.device, type(exc).__name__)
            return self._run(self._fall_back(model), audio, options)

    def _run(
        self, model: Any, audio: np.ndarray, options: dict[str, Any]
    ) -> tuple[str, str | None]:
        segments, info = model.transcribe(audio, **options)
        # Segments are a generator: the decoding happens here, inside the caller's try.
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return text, getattr(info, "language", None)

    def _ensure_model(self) -> Any:
        with self._lock:
            if self._model is None:
                self._model = self._load()
            return self._model

    def _load(self) -> Any:
        config = self.config
        try:
            model = self._factory(config.model_size, config.device, config.compute_type)
        except Exception as exc:
            if config.device == FALLBACK_DEVICE:
                raise
            log.warning("whisper load on %s failed: %s", config.device, type(exc).__name__)
            return self._load_fallback()
        self.device = config.device
        return model

    def _load_fallback(self) -> Any:
        model = self._factory(self.config.model_size, FALLBACK_DEVICE, FALLBACK_COMPUTE_TYPE)
        self.device = FALLBACK_DEVICE
        log.warning("whisper is running on %s/%s", FALLBACK_DEVICE, FALLBACK_COMPUTE_TYPE)
        return model

    def _fall_back(self, failed: Any) -> Any:
        """Swap the failed model for a CPU one, unless another thread already did."""
        with self._lock:
            if self._model is failed:
                self._model = self._load_fallback()
            return self._model


def load_transcriber() -> StreamTranscriber:
    """The app's transcriber, with the model, device and compute type from .env."""
    settings = get_settings()
    return StreamTranscriber(
        SttConfig(
            model_size=settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
    )


def pcm_duration_s(pcm: bytes) -> float:
    """Seconds of audio in a PCM buffer at the contracted sample rate."""
    return len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH_BYTES)
