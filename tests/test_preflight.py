"""Preflight verdicts that need no model: what blocks a demo and what only warns.

The real Whisper decode is `python -m server.preflight` itself. Here CTranslate2 is a
stand-in, so no test loads the real library or a model.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from server import preflight
from server.config import FirebaseSettings


def fake_ctranslate2(cuda_devices: int) -> SimpleNamespace:
    return SimpleNamespace(
        __version__="0.0-test",
        get_cuda_device_count=lambda: cuda_devices,
        get_supported_compute_types=lambda device: {"float16"} if cuda_devices else set(),
    )


def test_no_cuda_device_is_a_warning_and_does_not_block(monkeypatch, capsys):
    # CPU/int8 is the documented normal path: a laptop without CUDA must still pass.
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ctranslate2(cuda_devices=0))

    assert preflight.check_ctranslate2() is True

    printed = capsys.readouterr().out
    assert printed.startswith("WARN  ")
    assert "no CUDA device" in printed and "cpu/int8" in printed
    assert "FAIL" not in printed


def test_a_cuda_device_is_a_pass(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ctranslate2(cuda_devices=1))

    assert preflight.check_ctranslate2() is True
    assert capsys.readouterr().out.startswith("PASS  ")


def test_a_ctranslate2_that_will_not_import_still_blocks(monkeypatch, capsys):
    # None in sys.modules makes `import ctranslate2` raise ImportError.
    monkeypatch.setitem(sys.modules, "ctranslate2", None)

    assert preflight.check_ctranslate2() is False
    assert capsys.readouterr().out.startswith("FAIL  ")


def env_settings(firebase: FirebaseSettings | None) -> SimpleNamespace:
    """The settings `check_env` reads, with no key of any kind."""
    return SimpleNamespace(
        firebase=firebase,
        explainer_provider="anthropic",
        has_anthropic=False,
        has_gemini=False,
        has_ntfy=False,
    )


def test_preflight_says_when_the_page_makes_the_explainers_model_call(capsys):
    firebase = FirebaseSettings(api_key="key", project_id="second-ear-test", app_id="app")

    assert preflight.check_env(env_settings(firebase)) is True

    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("PASS  ") and "Firebase AI Logic" in first
    assert "second-ear-test" in first and firebase.model in first
    leaked = "key" in first.replace("second-ear-test", "")
    assert leaked is False  # the project and the model are named, the API key is not


def test_no_firebase_is_a_warning_and_does_not_block(capsys):
    assert preflight.check_env(env_settings(None)) is True

    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("WARN  ") and "FIREBASE_API_KEY" in first
    assert "the server's own explainer answers" in first


@pytest.mark.parametrize("cuda_devices", [0, 1])
def test_preflight_is_ok_with_or_without_cuda(monkeypatch, capsys, cuda_devices):
    # Whisper is skipped here, so this is the import checks alone: CUDA or not, they pass.
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ctranslate2(cuda_devices))
    monkeypatch.setattr(preflight, "check_import_isolation", lambda: True)

    assert preflight.main(["--skip-whisper"]) == 0
    assert "BLOCKED" not in capsys.readouterr().out
