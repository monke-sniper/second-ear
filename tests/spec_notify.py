"""Behaviour specs for the ntfy push. Green since Phase 4.

The fake client records the POST. A real push is checked by scripts/smoke_push.py.
"""

from __future__ import annotations

import json
import logging
import re
from types import SimpleNamespace

from server.contracts import ExplainerResult
from server.notify import NtfyNotifier

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


class RaisingClient:
    """Fails the way a dead network does, with the address in the message."""

    def __init__(self) -> None:
        self.calls = 0

    def post(self, url, **kwargs):
        self.calls += 1
        raise RuntimeError("https://ntfy.test/test-topic-abc123 refused the connection")


def test_a_failed_post_is_not_retried():
    fake = FakeClient(status_code=500)
    notifier = make_notifier(fake)
    assert notifier.send_scam(RESULT) is False
    assert notifier.send_scam(RESULT) is False
    assert len(fake.posts) == 1
    assert notifier.sent["scam"] is False
    assert notifier.last_code == "repeat"


def test_a_raising_client_reports_false_and_keeps_the_topic_out_of_the_log(caplog):
    caplog.set_level(logging.DEBUG)
    client = RaisingClient()
    notifier = make_notifier(client)
    assert notifier.send_code() is False
    assert notifier.send_code() is False
    assert client.calls == 1
    assert "test-topic-abc123" not in caplog.text
    assert "push failed: error:RuntimeError" in caplog.text


def test_no_digit_reaches_the_title_or_the_body():
    noisy = RESULT.model_copy(
        update={"reason": "Asked for 3 cards, code 4111 1111 1111 1111, pin four eight one five."}
    )
    fake = FakeClient()
    notifier = make_notifier(fake)
    notifier.send_scam(noisy)
    notifier.send_code()
    texts = [kwargs["json"]["title"] + kwargs["json"]["message"] for _, kwargs in fake.posts]
    leaked = any(char.isdigit() for text in texts for char in text)
    spoken = any("four eight" in text for text in texts)
    assert len(texts) == 2
    assert leaked is False
    assert spoken is False


def test_a_degraded_result_sends_the_fixed_body():
    degraded = RESULT.model_copy(update={"degraded": True, "reason": "anything at all"})
    fake = FakeClient()
    make_notifier(fake).send_scam(degraded)
    assert "anything at all" not in fake.posts[0][1]["json"]["message"]


def test_the_topic_travels_in_the_body_not_the_url():
    fake = FakeClient()
    make_notifier(fake).send_code()
    url, kwargs = fake.posts[0]
    assert url == "https://ntfy.test"
    assert kwargs["json"]["topic"] == "test-topic-abc123"
    assert kwargs["json"]["priority"] == 4
