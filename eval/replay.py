"""One recording through the app's own chunker, Whisper and call session, offline.

In: a 16 kHz mono 16-bit wav. Out: every step the live call would have produced, in
order, with the end-of-call tail heard the way server/live.py hears it.
It does not explain, push, write files or hold any rule; it only calls the server's code.
"""

from __future__ import annotations

import wave
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from server.chunker import AudioChunker, is_silent
from server.contracts import FRAME_BYTES, SAMPLE_RATE, SAMPLE_WIDTH_BYTES, TranscriptChunk
from server.pipeline import CallSession, Step
from server.scorer import RiskScorer
from server.stt import pcm_duration_s

# When a call ends, what no chunk had closed over is still heard from half a second up.
# The live socket does the same with END_TAIL_MIN_S in server/live.py.
TAIL_MIN_S = 0.5
CONVERT = "ffmpeg -i {name} -ac 1 -ar 16000 -c:a pcm_s16le fixed_{name}"


class WavFormatError(ValueError):
    """The file is not 16 kHz mono 16-bit PCM. The message says how to convert it."""


class Transcriber(Protocol):
    def transcribe(self, pcm: bytes, *, start_s: float = 0.0) -> TranscriptChunk: ...


@dataclass(frozen=True)
class Replay:
    """What one recording produced. `chunks` is raw text and must stay in memory."""

    duration_s: float
    steps: tuple[Step, ...]
    chunks: tuple[TranscriptChunk, ...]
    tail_s: float  # seconds of unclosed audio handed to the session at the end, 0 if none


def read_wav(path: Path) -> bytes:
    """The PCM of a recording. Any other format is refused, never resampled quietly."""
    try:
        with wave.open(str(path), "rb") as wav:
            shape = (wav.getframerate(), wav.getnchannels(), wav.getsampwidth())
            pcm = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError) as exc:
        raise WavFormatError(f"{path.name}: not a PCM wav. Convert: {CONVERT.format(name=path.name)}") from exc
    if shape != (SAMPLE_RATE, 1, SAMPLE_WIDTH_BYTES):
        raise WavFormatError(
            f"{path.name}: {shape[0]} Hz, {shape[1]} channel(s), {shape[2] * 8}-bit; needs 16000 Hz "
            f"mono 16-bit. Convert: {CONVERT.format(name=path.name)}"
        )
    return pcm


def replay_call(pcm: bytes, transcriber: Transcriber, scorer: RiskScorer) -> Replay:
    """Feed the recording as 250 ms frames, exactly as the socket would.

    Each chunk takes the path of `LiveCall._hear`: a quiet chunk skips Whisper, any other
    is transcribed, and the session turns the text into events. A Whisper failure is not
    hidden here: it stops the run, because a call scored on missing text is a wrong number.
    """
    chunker = AudioChunker()
    session = CallSession(scorer)
    steps: list[Step] = []

    def hear(chunk: bytes) -> None:
        text = ""
        if not is_silent(chunk, chunker.config.pause_db):
            text = transcriber.transcribe(chunk, start_s=session.now_s).text
        steps.append(session.ingest(text, pcm_duration_s(chunk)))

    for start in range(0, len(pcm), FRAME_BYTES):
        for chunk in chunker.feed(pcm[start : start + FRAME_BYTES]):
            hear(chunk)

    # End of the recording: `flush()` returns a tail of at least `min_s`, so lower it.
    left_s = chunker.buffered_s
    chunker.config = replace(chunker.config, min_s=TAIL_MIN_S)
    tail = chunker.flush()
    if tail is not None:
        hear(tail)
    elif left_s:
        session.ingest("", left_s)  # too short to hear; the clock still reaches the end
    return Replay(
        duration_s=session.now_s,
        steps=tuple(steps),
        chunks=session.chunks,
        tail_s=pcm_duration_s(tail) if tail is not None else 0.0,
    )
