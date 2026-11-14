"""The transcriber's contract, with a fake in place of faster-whisper.

The real model is checked by `python -m server.preflight`, not here: no test may load
Whisper or touch the GPU.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.stt import SttConfig, StreamTranscriber, decode_options
from tests.helpers import tone_frame


class FakeModel:
    def __init__(self, device: str, fails: bool = False) -> None:
        self.device = device
        self.fails = fails
        self.calls: list[dict] = []

    def transcribe(self, audio, **kwargs):
        self.calls.append({"samples": len(audio), **kwargs})
        if self.fails:
            raise RuntimeError("cuda decode failed")
        segments = (SimpleNamespace(text=part) for part in (" hello there", " grandma "))
        return segments, SimpleNamespace(language="en")


class FakeFactory:
    """Builds FakeModels and records every load. `broken` devices fail as named."""

    def __init__(self, load_fails_on: str | None = None, decode_fails_on: str | None = None):
        self.load_fails_on = load_fails_on
        self.decode_fails_on = decode_fails_on
        self.loads: list[tuple[str, str, str]] = []
        self.models: list[FakeModel] = []

    def __call__(self, model_size: str, device: str, compute_type: str) -> FakeModel:
        self.loads.append((model_size, device, compute_type))
        if device == self.load_fails_on:
            raise RuntimeError("no cuda here")
        model = FakeModel(device, fails=device == self.decode_fails_on)
        self.models.append(model)
        return model


def test_english_only_models_transcribe_in_english():
    options = decode_options(SttConfig(model_size="base.en"))

    assert options["language"] == "en"
    assert options["task"] == "transcribe"


def test_other_models_translate_into_english():
    options = decode_options(SttConfig(model_size="small"))

    assert options["language"] is None
    assert options["task"] == "translate"


def test_every_decode_is_independent_and_vad_filtered():
    factory = FakeFactory()
    transcriber = StreamTranscriber(model_factory=factory)

    transcriber.transcribe(tone_frame() * 8)

    call = factory.models[0].calls[0]
    assert call["condition_on_previous_text"] is False
    assert call["vad_filter"] is True
    assert call["beam_size"] == 1


def test_transcribe_joins_segments_and_times_the_chunk():
    transcriber = StreamTranscriber(model_factory=FakeFactory())

    result = transcriber.transcribe(tone_frame() * 10, start_s=12.0)

    assert result.text == "hello there grandma"
    assert result.start_s == 12.0
    assert result.end_s == 14.5
    assert result.language == "en"


def test_the_model_loads_once_and_lazily():
    factory = FakeFactory()
    transcriber = StreamTranscriber(model_factory=factory)
    assert transcriber.is_loaded is False

    transcriber.transcribe(tone_frame() * 8)
    transcriber.transcribe(tone_frame() * 8)

    assert factory.loads == [("base.en", "cuda", "float16")]
    assert transcriber.device == "cuda"


def test_a_failed_cuda_load_falls_back_to_cpu_int8():
    factory = FakeFactory(load_fails_on="cuda")
    transcriber = StreamTranscriber(model_factory=factory)

    result = transcriber.transcribe(tone_frame() * 8)

    assert result.text == "hello there grandma"
    assert factory.loads == [("base.en", "cuda", "float16"), ("base.en", "cpu", "int8")]
    assert transcriber.device == "cpu"


def test_a_failed_cuda_decode_falls_back_to_cpu_and_stays_there():
    factory = FakeFactory(decode_fails_on="cuda")
    transcriber = StreamTranscriber(model_factory=factory)

    first = transcriber.transcribe(tone_frame() * 8)
    second = transcriber.transcribe(tone_frame() * 8)

    assert first.text == second.text == "hello there grandma"
    assert [device for _size, device, _type in factory.loads] == ["cuda", "cpu"]


def test_a_cpu_failure_is_raised_not_retried():
    factory = FakeFactory(load_fails_on="cpu")
    transcriber = StreamTranscriber(SttConfig(device="cpu", compute_type="int8"), factory)

    with pytest.raises(RuntimeError):
        transcriber.transcribe(tone_frame() * 8)
    assert len(factory.loads) == 1


def test_warmup_loads_the_model_and_decodes_one_second():
    factory = FakeFactory()
    transcriber = StreamTranscriber(model_factory=factory)

    transcriber.warmup()

    assert transcriber.is_loaded is True
    assert factory.models[0].calls[0]["samples"] == 16_000


def test_warmup_decodes_with_the_vad_off_so_the_device_is_really_used():
    factory = FakeFactory()
    transcriber = StreamTranscriber(model_factory=factory)

    transcriber.warmup()
    transcriber.transcribe(tone_frame() * 8)

    warm, live = factory.models[0].calls
    assert warm["vad_filter"] is False
    assert live["vad_filter"] is True  # the override never leaks into a real chunk


def test_warmup_moves_to_the_cpu_when_cuda_cannot_decode():
    factory = FakeFactory(decode_fails_on="cuda")
    transcriber = StreamTranscriber(model_factory=factory)

    transcriber.warmup()

    assert transcriber.device == "cpu"
    assert [device for _size, device, _type in factory.loads] == ["cuda", "cpu"]


def test_half_a_sample_is_rejected():
    transcriber = StreamTranscriber(model_factory=FakeFactory())

    with pytest.raises(ValueError):
        transcriber.transcribe(b"\x00\x00\x00")
