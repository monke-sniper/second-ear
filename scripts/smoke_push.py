"""Sends one clearly labelled test push through the real NtfyNotifier.

It prints whether the push was sent and the reason code. It never prints the topic.
Run from the repo root once .env has NTFY_TOPIC: python scripts/smoke_push.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.contracts import ExplainerResult  # noqa: E402
from server.explainer import GENERIC_SAFE_EXIT  # noqa: E402
from server.notify import NtfyNotifier  # noqa: E402

TEST_RESULT = ExplainerResult(
    scam_type="other",
    reason="This is a test push from the smoke script. No call is happening.",
    safe_exit_line=GENERIC_SAFE_EXIT,
)


def main() -> int:
    notifier = NtfyNotifier()
    topic_state = "set" if notifier.enabled else "missing or placeholder"
    print(f"server={notifier.base_url} topic={topic_state}")
    sent = notifier.send_scam(TEST_RESULT)
    print(f"push: sent={sent} code={notifier.last_code}")
    return 0 if sent else 1


if __name__ == "__main__":
    sys.exit(main())
