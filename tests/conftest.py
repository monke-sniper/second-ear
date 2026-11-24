"""Fixtures shared by the plumbing tests and the behaviour specs.

The doubles and PCM helpers live in tests/helpers.py so test modules can import
them directly. Every app built here gets fakes for Whisper, Anthropic and ntfy, so
no test can load a model, spend a token or reach a real phone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Sequence

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import FirebaseSettings, get_settings
from server.explainer import TIMEOUT_S, Explainer
from server.live import Services
from server.notify import NtfyNotifier
from server.scorer import StubScorer
from tests.helpers import FAKE_ORGS, FakeAnthropic, FakeHttp, FakeTranscriber, ScriptedScorer


@dataclass
class Harness:
    """A test app and the doubles behind it."""

    transcriber: FakeTranscriber = field(default_factory=FakeTranscriber)
    scorer: object = field(default_factory=StubScorer)
    anthropic: FakeAnthropic = field(default_factory=FakeAnthropic)
    http: FakeHttp = field(default_factory=FakeHttp)
    calls_dir: Path | None = None  # where /demo/audio looks; None is the real folder
    firebase: FirebaseSettings | None = None  # set, the page is asked to explain an alert
    explainer_timeout_s: float = TIMEOUT_S

    def notifier(self) -> NtfyNotifier:
        return NtfyNotifier(topic="test-topic", base_url="https://ntfy.test", client=self.http)

    def explainer(self) -> Explainer:
        return Explainer(client=self.anthropic, orgs=FAKE_ORGS, timeout_s=self.explainer_timeout_s)

    def client(self) -> TestClient:
        return TestClient(
            create_app(
                transcriber=self.transcriber,
                scorer=self.scorer,
                explainer=self.explainer(),
                notifier_factory=self.notifier,
                calls_dir=self.calls_dir,
                firebase=self.firebase,
            )
        )

    def services(self) -> Services:
        """The same doubles, for a test that runs `LiveCall` without the app around it."""
        return Services(
            transcriber=self.transcriber,
            scorer=self.scorer,
            explainer=self.explainer(),
            notifier_factory=self.notifier,
            ask_page=self.firebase is not None,
        )


def scripted(texts: Sequence[str], scores: Sequence[float], **doubles: object) -> Harness:
    """A harness whose Whisper says `texts` and whose scorer returns `scores`."""
    return Harness(
        transcriber=FakeTranscriber(texts), scorer=ScriptedScorer(scores), **doubles
    )


@pytest.fixture(autouse=True)
def no_real_model_keys(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No test may reach a real model, whatever .env holds.

    Both provider keys are blanked and the provider is the default for every test, so an
    Explainer built without a client finds no key and makes no request. A test that needs
    a key or the other provider sets it itself. The Firebase values are blanked as well,
    so an app built without `firebase=` never asks the page to explain.
    """
    for name in (
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "FIREBASE_API_KEY",
        "FIREBASE_PROJECT_ID",
        "FIREBASE_APP_ID",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("EXPLAINER_PROVIDER", "anthropic")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with Harness().client() as test_client:
        yield test_client
