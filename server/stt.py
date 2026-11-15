"""Speech to text, one audio chunk at a time.

In: one 2–6 s chunk of 16 kHz mono s16le PCM.
Out: English text with its time window inside the call, from faster-whisper on the GPU.
A segment that Whisper's own numbers mark as a failed decode (a repetition loop, or words
over silence) is dropped before the text is built.
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
# One pass per chunk. faster-whisper's default retries a doubtful decode at five higher
# temperatures; on cpu/int8 that took a 6 s chunk of read-out digits to about 16 s
# (docs/SPEC.md §10), far too late for a code warning.
TEMPERATURE = 0.0

# The hallucination guard. These are Whisper's reference thresholds (its
# compression_ratio_threshold, no_speech_threshold and logprob_threshold defaults) and are
# not tuned here. Whisper uses the first to ask for a retry at a higher temperature; with
# one pass per chunk there is no retry, so a segment that fails is dropped instead.
MAX_COMPRESSION_RATIO = 2.4  # above this the text repeats itself: "a little bit of a little bit of"
MAX_NO_SPEECH_PROB = 0.6  # above this, with the next line, the words were made up over silence
MIN_AVG_LOGPROB = -1.0
# The reason codes. A drop is logged by its code and nothing else.
DROP_REPETITION = "compression_ratio"
DROP_NO_SPEECH = "no_speech"

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
    `temperature=0.0` means one decode per chunk and no retries.
    """
    english_only = config.model_size.endswith(ENGLISH_ONLY_SUFFIX)
    return {
        "language": "en" if english_only else config.language,
        "task": "transcribe" if english_only else config.task,
        "vad_filter": config.vad_filter,
        "beam_size": config.beam_size,
        "condition_on_previous_text": False,
        "temperature": TEMPERATURE,
    }


def drop_reason(segment: Any) -> str | None:
    """Why a decoded segment is thrown away, or None to keep it.

    Reads faster-whisper's own fields on the segment: `compression_ratio`, `no_speech_prob`
    and `avg_logprob`. The comparisons are strict, as in Whisper. A segment without a
    field is not judged on it.
    """
    ratio = getattr(segment, "compression_ratio", None)
    if ratio is not None and ratio > MAX_COMPRESSION_RATIO:
        return DROP_REPETITION
    no_speech = getattr(segment, "no_speech_prob", None)
    logprob = getattr(segment, "avg_logprob", None)
    if no_speech is None or logprob is None:
        return None
    if no_speech > MAX_NO_SPEECH_PROB and logprob < MIN_AVG_LOGPROB:
        return DROP_NO_SPEECH
    return None


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
        happens here, at startup. Whatever Whisper invents for silence is discarded,
        and a segment the guard drops here is not logged: it is not from a call.
        """
        self._decode(np.zeros(SAMPLE_RATE, dtype=np.float32), log_drops=False, vad_filter=False)

    def transcribe(self, pcm: bytes, *, start_s: float = 0.0) -> TranscriptChunk:
        """Transcribe one chunk.

        `start_s` is the chunk's offset in the call; the returned `end_s` is
        `start_s + len(pcm) / 32_000` because the audio is 16 kHz s16le.
        Empty speech returns an empty `text`, never "thank you" — `vad_filter` is on.
        A segment that fails `drop_reason` is left out, so a chunk that was only a
        hallucination also returns an empty `text`.
        """
        text, language = self._decode(pcm16_to_float32(pcm))
        return TranscriptChunk(
            text=text, start_s=start_s, end_s=start_s + pcm_duration_s(pcm), language=language
        )

    def reset(self) -> None:
        """Nothing to forget: each chunk is decoded on its own. The model stays loaded."""
        return None

    def _decode(
        self, audio: np.ndarray, *, log_drops: bool = True, **overrides: Any
    ) -> tuple[str, str | None]:
        """Run Whisper, and once on the CPU if the configured device fails."""
        options = {**decode_options(self.config), **overrides}
        model = self._ensure_model()
        try:
            return self._run(model, audio, options, log_drops)
        except Exception as exc:
            if self.device == FALLBACK_DEVICE:
                raise
            # CUDA can load and still fail on the first real decode (a missing DLL).
            log.warning("whisper decode on %s failed: %s", self.device, type(exc).__name__)
            return self._run(self._fall_back(model), audio, options, log_drops)

    def _run(
        self, model: Any, audio: np.ndarray, options: dict[str, Any], log_drops: bool = True
    ) -> tuple[str, str | None]:
        segments, info = model.transcribe(audio, **options)
        kept: list[str] = []
        # Segments are a generator: the decoding happens here, inside the caller's try.
        for segment in segments:
            reason = drop_reason(segment)
            if reason is None:
                kept.append(segment.text.strip())
            elif log_drops:
                # The code only. Never the text, which may be what was said on the call.
                log.warning("whisper segment dropped: %s", reason)
        return " ".join(kept).strip(), getattr(info, "language", None)

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
