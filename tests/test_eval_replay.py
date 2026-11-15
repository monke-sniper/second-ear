"""The offline replay: frames in, the session's steps out, and the end-of-call tail.

Made-up PCM, a fake Whisper and a fake scorer. The digits in these tests are invented and
assertions are booleans, so a failure prints none of them.
"""

from __future__ import annotations

import struct
import wave

import pytest

from eval import replay as replay_module
from eval.replay import WavFormatError, read_wav, replay_call
from server import live
from server.contracts import FRAME_BYTES, TranscriptChunk
from server.stt import pcm_duration_s


def tone(frames: int) -> bytes:
    return struct.pack("<h", 1000) * (FRAME_BYTES // 2) * frames


def quiet(frames: int) -> bytes:
    return b"\x00\x00" * (FRAME_BYTES // 2) * frames


SPOKEN = tone(8) + quiet(2)  # the chunker closes this as one 2.5 s chunk


class Says:
    """A Whisper that returns its texts in order, then repeats the last one."""

    def __init__(self, texts, raises: Exception | None = None) -> None:
        self.texts = list(texts)
        self.raises = raises
        self.calls: list[int] = []

    def transcribe(self, pcm: bytes, *, start_s: float = 0.0) -> TranscriptChunk:
        if self.raises is not None:
            raise self.raises
        self.calls.append(len(pcm))
        text = self.texts[min(len(self.calls) - 1, len(self.texts) - 1)]
        return TranscriptChunk(text=text, start_s=start_s, end_s=start_s + pcm_duration_s(pcm))


class Always:
    name = "fake-scorer"

    def __init__(self, value: float) -> None:
        self.value = value

    def score(self, transcript: str) -> float:
        return self.value


def write_wav(path, pcm: bytes, rate: int = 16000, channels: int = 1) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)


def test_a_code_read_in_the_last_second_is_heard_and_fires_the_warning():
    whisper = Says(["we need to talk", "the code is 4 1 5 9 2 6"])

    replay = replay_call(SPOKEN + tone(4), whisper, Always(0.9))

    assert len(whisper.calls) == 2
    assert replay.tail_s == 1.0 and replay.duration_s == 3.5
    assert replay.steps[-1].danger is not None
    assert replay.steps[-1].alert is not None
    assert len(replay.chunks) == 2


def test_a_tail_under_half_a_second_is_not_heard_but_the_clock_reaches_the_end():
    whisper = Says(["we need to talk", "never heard"])

    replay = replay_call(SPOKEN + tone(1), whisper, Always(0.1))

    assert len(whisper.calls) == 1
    assert replay.tail_s == 0.0 and replay.duration_s == 2.75
    assert len(replay.steps) == 1


def test_a_quiet_tail_never_reaches_whisper():
    whisper = Says(["we need to talk", "never heard"])

    replay = replay_call(SPOKEN + quiet(4), whisper, Always(0.1))

    assert len(whisper.calls) == 1
    assert replay.duration_s == 3.5
    assert replay.steps[-1].transcript is None


def test_a_recording_cut_by_the_chunker_alone_has_no_tail():
    replay = replay_call(SPOKEN + SPOKEN, Says(["one moment", "thank you"]), Always(0.1))

    assert replay.tail_s == 0.0 and replay.duration_s == 5.0
    assert [step.transcript is not None for step in replay.steps] == [True, True]


def test_the_tail_rule_is_the_live_socket_s_own_constant(monkeypatch):
    assert replay_module.END_TAIL_MIN_S is live.END_TAIL_MIN_S
    assert not hasattr(replay_module, "TAIL_MIN_S")  # no second copy to drift

    # And the replay obeys it: with the minimum raised, a one-second tail is not heard.
    monkeypatch.setattr(replay_module, "END_TAIL_MIN_S", 1.5)
    whisper = Says(["we need to talk", "never heard"])
    replay = replay_call(SPOKEN + tone(4), whisper, Always(0.1))
    assert len(whisper.calls) == 1 and replay.tail_s == 0.0


def test_a_whisper_failure_stops_the_replay_instead_of_passing_for_silence():
    with pytest.raises(RuntimeError):
        replay_call(SPOKEN, Says([], raises=RuntimeError("decode failed")), Always(0.1))


def test_read_wav_takes_16k_mono_and_refuses_anything_else(tmp_path):
    good = tmp_path / "good.wav"
    write_wav(good, SPOKEN)
    assert read_wav(good) == SPOKEN

    for name, kwargs in (("slow.wav", {"rate": 8000}), ("stereo.wav", {"channels": 2})):
        write_wav(tmp_path / name, SPOKEN, **kwargs)
        with pytest.raises(WavFormatError) as caught:
            read_wav(tmp_path / name)
        assert "ffmpeg" in str(caught.value) and "pcm_s16le" in str(caught.value)

    (tmp_path / "notes.wav").write_text("not audio", encoding="utf-8")
    with pytest.raises(WavFormatError):
        read_wav(tmp_path / "notes.wav")
