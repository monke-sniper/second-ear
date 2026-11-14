"""Behaviour specs for the ntfy push. Strict-xfail until Phase 4 lands."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

from server.contracts import ExplainerResult
from server.notify import NtfyNotifier

pytestmark = pytest.mark.xfail(strict=True, reason="push lands in phase 4 — docs/SPEC.md §5")

RESULT = ExplainerResult(
    scam_type="gift_card",
    reason="Asked for gift card codes.",
    safe_exit_line="I'll call you back at the number on my card.",
    claimed_org="chase",
    org_name="Chase",
    official_number="555-0100",
)


class FakeClient:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.posts: list[tuple[str, dict]] = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return SimpleNamespace(status_code=self.status_code, text="ok")


def make_notifier(fake: FakeClient) -> NtfyNotifier:
    return NtfyNotifier(topic="test-topic-abc123", base_url="https://ntfy.test", client=fake)


def test_one_scam_push_per_call():
    fake = FakeClient()
    notifier = make_notifier(fake)
    assert notifier.send_scam(RESULT) is True
    assert notifier.send_scam(RESULT) is False
    assert len(fake.posts) == 1


def test_no_push_payload_contains_a_digit_run():
    fake = FakeClient()
    make_notifier(fake).send_scam(RESULT)
    url, kwargs = fake.posts[0]
    payload = json.dumps({"url": url, **kwargs}, default=str)
    assert re.search(r"\d{6,}", payload) is None


def test_code_push_is_independent_of_the_scam_push():
    fake = FakeClient()
    notifier = make_notifier(fake)
    assert notifier.send_scam(RESULT) is True
    assert notifier.send_code() is True
    assert notifier.send_code() is False
    assert len(fake.posts) == 2


def test_reset_rearms_both_push_types():
    fake = FakeClient()
    notifier = make_notifier(fake)
    notifier.send_scam(RESULT)
    notifier.send_code()
    notifier.reset()
    assert notifier.send_scam(RESULT) is True
    assert notifier.send_code() is True


def test_a_placeholder_topic_disables_pushes():
    fake = FakeClient()
    notifier = NtfyNotifier(topic="second-ear-replace-with-random", client=fake)
    assert notifier.enabled is False
    assert notifier.send_scam(RESULT) is False
    assert fake.posts == []


def test_a_failed_post_reports_false():
    fake = FakeClient(status_code=500)
    assert make_notifier(fake).send_scam(RESULT) is False
