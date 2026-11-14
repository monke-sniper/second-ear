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
from server.explainer import Explainer
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

    def notifier(self) -> NtfyNotifier:
        return NtfyNotifier(topic="test-topic", base_url="https://ntfy.test", client=self.http)

    def client(self) -> TestClient:
        return TestClient(
            create_app(
                transcriber=self.transcriber,
                scorer=self.scorer,
                explainer=Explainer(client=self.anthropic, orgs=FAKE_ORGS),
                notifier_factory=self.notifier,
                calls_dir=self.calls_dir,
            )
        )


def scripted(texts: Sequence[str], scores: Sequence[float], **doubles: object) -> Harness:
    """A harness whose Whisper says `texts` and whose scorer returns `scores`."""
    return Harness(
        transcriber=FakeTranscriber(texts), scorer=ScriptedScorer(scores), **doubles
    )


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with Harness().client() as test_client:
        yield test_client
