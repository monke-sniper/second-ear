"""The family push over ntfy. One per alert type per call.

In: an ExplainerResult for a scam, or nothing for a code warning.
Out: True when a push was sent, False when it was a repeat, disabled, or failed.
It never includes digits, never retries, and never blocks the alert path.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import TYPE_CHECKING, Any

from server.config import get_settings
from server.contracts import ExplainerResult
from server.explainer import REDACTED, redact_digits

if TYPE_CHECKING:
    import httpx

log = logging.getLogger("second_ear.notify")

# ntfy limits, with room to spare.
MAX_TITLE = 120
MAX_BODY = 512
# ntfy priority scale is 1–5; 4 is "high" (docs.ntfy.sh/publish, checked Nov 14).
PRIORITY_HIGH = 4
# Not in SPEC: how long one push may hold the thread that sends it.
POST_TIMEOUT_S = 3.0
# A spoken number of this many digits is removed from a push, like a written one.
SPOKEN_NUMBER_MIN = 2

SCAM_TITLE = "Second Ear: this sounds like a scam"
SCAM_BODY_GENERIC = "A call happening now sounds like a scam."
CODE_TITLE = "Second Ear: a number is being read aloud"
CODE_BODY = (
    "Someone on the call is reading a long number aloud. It could be a card number or a code."
)
SCAM_LABELS = {
    "grandparent": "Grandparent scam",
    "medicare": "Medicare scam",
    "ssn": "Social Security scam",
    "refund": "Refund scam",
    "tech_support": "Tech support scam",
    "gift_card": "Gift card scam",
    "reward": "Prize scam",
    "romance": "Romance scam",
    "bank_fraud": "Bank fraud scam",
    "other": "Possible scam",
}

_ANY_DIGIT = re.compile(r"\d+")


def _scrub(text: str) -> str:
    """No digit may reach a push: spoken and long numbers first, then any digit left."""
    return _ANY_DIGIT.sub(REDACTED, redact_digits(text, SPOKEN_NUMBER_MIN))


def _scam_body(result: ExplainerResult) -> str:
    """Scam type and reason. Never the transcript, the line to say, or the callback number."""
    if result.degraded:
        return SCAM_BODY_GENERIC
    label = SCAM_LABELS.get(result.scam_type, SCAM_LABELS["other"])
    return _scrub(f"{label}: {result.reason}")


class NtfyNotifier:
    """Per-call push gate.

    `send_scam` and `send_code` are each attempted at most once per call, whether or
    not the attempt succeeds; `reset()` is called when a new call starts. A missing
    topic disables the notifier instead of raising, so a missing .env never takes the
    app down mid-demo. `client` is an `httpx.Client`-shaped object; tests pass a fake.
    `last_code` says how the last send ended ("ok", "repeat", "disabled", "http_503",
    "error:ConnectError"); it never holds the topic.
    """

    def __init__(
        self,
        topic: str | None = None,
        base_url: str | None = None,
        client: "httpx.Client | None" = None,
    ) -> None:
        settings = get_settings()
        self.topic = topic or settings.ntfy_topic
        self.base_url = (base_url or settings.ntfy_base_url).rstrip("/")
        self._client = client
        self._lock = threading.Lock()
        self._tried_scam = False
        self._tried_code = False
        self._sent_scam = False
        self._sent_code = False
        self.last_code: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.topic and not str(self.topic).startswith("second-ear-replace"))

    def send_scam(self, result: ExplainerResult) -> bool:
        """POST one high-priority push naming the scam type and the reason.

        Title and body are built from `result`; the transcript never goes in the
        body, so there is nothing to leak. Returns False on the second call, even
        when the first one failed: one attempt per call, never a retry.
        """
        with self._lock:
            if not self._may_try(self._tried_scam):
                return False
            self._tried_scam = True
        self._sent_scam = self._post(SCAM_TITLE, _scam_body(result))
        return self._sent_scam

    def send_code(self) -> bool:
        """POST one high-priority push for a detected digit run.

        The body says a number was read aloud; it does not say which. Returns False
        on the second call, even when the first one failed.
        """
        with self._lock:
            if not self._may_try(self._tried_code):
                return False
            self._tried_code = True
        self._sent_code = self._post(CODE_TITLE, CODE_BODY)
        return self._sent_code

    def reset(self) -> None:
        """Re-arm both push types for a new call."""
        with self._lock:
            self._tried_scam = False
            self._tried_code = False
            self._sent_scam = False
            self._sent_code = False

    @property
    def sent(self) -> dict[str, bool]:
        """Read-only view for tests and the demo console: what was actually delivered."""
        return {"scam": self._sent_scam, "code": self._sent_code}

    def _may_try(self, already_tried: bool) -> bool:
        if not self.enabled:
            self.last_code = "disabled"
            return False
        if already_tried:
            self.last_code = "repeat"
            return False
        return True

    def _post(self, title: str, body: str) -> bool:
        """One JSON publish to the ntfy root URL. True only on a 2xx answer.

        The topic travels in the JSON body, not the URL, so it cannot show up in an
        HTTP client's request log. Failures log a status or a class name, never the
        exception message.
        """
        payload = {
            "topic": self.topic,
            "title": title[:MAX_TITLE],
            "message": body[:MAX_BODY],
            "priority": PRIORITY_HIGH,
        }
        try:
            response = self._poster().post(self.base_url, json=payload, timeout=POST_TIMEOUT_S)
        except Exception as exc:  # a failed push must never take the alert down
            self.last_code = f"error:{type(exc).__name__}"
            log.warning("push failed: %s", self.last_code)
            return False
        if 200 <= response.status_code < 300:
            self.last_code = "ok"
            return True
        self.last_code = f"http_{response.status_code}"
        log.warning("push failed: %s", self.last_code)
        return False

    def _poster(self) -> Any:
        if self._client is not None:
            return self._client
        import httpx

        return httpx
