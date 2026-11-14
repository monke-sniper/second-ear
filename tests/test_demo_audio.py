"""GET /demo/audio: the recording the demo console replays, or a 404.

Each test points the app at its own empty folder, so no real recording is read.
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import Harness


def get(calls_dir: Path):
    with Harness(calls_dir=calls_dir).client() as client:
        return client.get("/demo/audio")


def test_no_recording_is_a_404(tmp_path):
    assert get(tmp_path).status_code == 404


def test_a_missing_folder_is_a_404_too(tmp_path):
    assert get(tmp_path / "not-here").status_code == 404


def test_the_recorded_call_is_served_as_wav_with_its_name(tmp_path):
    (tmp_path / "demo_scam.wav").write_bytes(b"recorded")

    response = get(tmp_path)

    assert response.status_code == 200
    assert response.content == b"recorded"
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["content-disposition"] == 'inline; filename="demo_scam.wav"'
    assert response.headers["cache-control"] == "no-store"


def test_the_synthetic_voice_is_the_fallback(tmp_path):
    (tmp_path / "tts_scam.wav").write_bytes(b"synthetic")

    response = get(tmp_path)

    assert response.status_code == 200
    assert response.content == b"synthetic"
    assert response.headers["content-disposition"] == 'inline; filename="tts_scam.wav"'


def test_the_recorded_call_wins_over_the_synthetic_voice(tmp_path):
    (tmp_path / "demo_scam.wav").write_bytes(b"recorded")
    (tmp_path / "tts_scam.wav").write_bytes(b"synthetic")

    assert get(tmp_path).content == b"recorded"


def test_other_files_in_the_folder_are_never_served(tmp_path):
    (tmp_path / "01_grandparent.wav").write_bytes(b"someone's voice")

    assert get(tmp_path).status_code == 404
