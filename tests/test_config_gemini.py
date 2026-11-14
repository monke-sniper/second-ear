"""Gemini settings: the key and the model id have one home, server/config.py.

Only eval/make_heldout.py uses them, to write the held-out test set.
Nothing here reaches the network or reads the real key.
"""

from __future__ import annotations

from typing import Iterator

import pytest

from server.config import DEFAULT_GEMINI_MODEL, ROOT, get_settings


@pytest.fixture()
def fresh_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Let a test set the environment, and have the real one re-read afterwards."""
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def test_the_gemini_key_and_model_come_from_the_environment(fresh_settings):
    fresh_settings.setenv("GEMINI_API_KEY", "test-key")
    fresh_settings.setenv("GEMINI_MODEL", "gemini-test")

    settings = get_settings()

    assert settings.gemini_api_key == "test-key"
    assert settings.gemini_model == "gemini-test"
    assert settings.has_gemini is True


def test_no_key_means_no_gemini_and_the_default_model(fresh_settings):
    fresh_settings.setenv("GEMINI_API_KEY", "")
    fresh_settings.delenv("GEMINI_MODEL", raising=False)

    settings = get_settings()

    assert settings.gemini_api_key is None
    assert settings.has_gemini is False
    assert settings.gemini_model == DEFAULT_GEMINI_MODEL


def test_env_example_documents_both_gemini_settings_and_holds_no_key():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()

    assert "GEMINI_API_KEY=" in lines
    assert f"GEMINI_MODEL={DEFAULT_GEMINI_MODEL}" in lines
