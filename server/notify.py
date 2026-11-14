"""The family push over ntfy. One per alert type per call.

In: an ExplainerResult for a scam, or nothing for a code warning.
Out: True when a push was sent, False when it was a repeat, disabled, or failed.
It never includes digits, never retries in a loop, and never blocks the alert path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.config import get_settings
from server.contracts import DangerDecision, ExplainerResult

if TYPE_CHECKING:
    import httpx

# ntfy limits, with room to spare.
MAX_TITLE = 120
MAX_BODY = 512


class NtfyNotifier:
    """Per-call push gate.

    `send_scam` and `send_code` each succeed at most once per call; `reset()` is
    called when a new call starts. A missing topic disables the notifier instead of
    raising, so a missing .env never takes the app down mid-demo. `client` is an
    `httpx.Client`-shaped object; tests pass a fake.
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
        self._sent_scam = False
        self._sent_code = False

    @property
    def enabled(self) -> bool:
        return bool(self.topic and not str(self.topic).startswith("second-ear-replace"))

    def send_scam(self, result: ExplainerResult) -> bool:
        """POST one high-priority push naming the scam type and the reason.

        Title and body are built from `result`; the transcript never goes in the
        body, so there is nothing to leak. Returns False on the second call.
        """
        raise NotImplementedError("push lands in phase 4 — docs/SPEC.md §5")

    def send_code(self) -> bool:
        """POST one high-priority push for a detected digit run.

        The body says a number was read aloud; it does not say which. Returns False
        on the second call.
        """
        raise NotImplementedError("push lands in phase 4 — docs/SPEC.md §5")

    def reset(self) -> None:
        """Re-arm both push types for a new call."""
        self._sent_scam = False
        self._sent_code = False

    @property
    def sent(self) -> dict[str, bool]:
        """Read-only view for tests and the demo console."""
        return {"scam": self._sent_scam, "code": self._sent_code}
