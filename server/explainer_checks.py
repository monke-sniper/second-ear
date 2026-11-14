"""Checks Haiku's reply before any of it can reach the screen or a push.

In: the raw reply text, the allowed scam types, and the known organisation ids.
Out: the four validated fields, or the name of the first check that failed.
It does not call the model, look up phone numbers, or log anything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Collection

from server.numbers import DIGIT_RUN, has_number_run

# Frozen by docs/SPEC.md §5.
SAFE_EXIT_MIN_CHARS = 3
SAFE_EXIT_MAX_CHARS = 160
REASON_MAX_CHARS = 120
# In the line the person says out loud, even a short spoken number is refused.
SPOKEN_NUMBER_MIN = 2

OK = "ok"
BAD_JSON = "bad_json"


@dataclass(frozen=True)
class Reply:
    """The model's answer after every SPEC §5 check has passed."""

    scam_type: str
    reason: str
    safe_exit_line: str
    claimed_org: str | None


def _parse_object(text: str) -> dict[str, Any] | None:
    """The JSON object in `text`, tolerating a code fence or a stray sentence around it."""
    stripped = text.strip()
    inner = stripped[stripped.find("{") : stripped.rfind("}") + 1]
    for candidate in (stripped, inner):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _reason_ok(reason: str) -> bool:
    # "Nothing on the wire ever carries a raw digit run" (docs/SPEC.md §3).
    return len(reason) <= REASON_MAX_CHARS and not has_number_run(reason, DIGIT_RUN)


def _safe_exit_ok(line: str) -> bool:
    if not SAFE_EXIT_MIN_CHARS <= len(line) <= SAFE_EXIT_MAX_CHARS:
        return False
    if any(char.isdigit() for char in line):
        return False
    return not has_number_run(line, SPOKEN_NUMBER_MIN)


def check_reply(
    text: str, scam_types: Collection[str], org_ids: Collection[str]
) -> tuple[Reply | None, str]:
    """Validate the reply. Returns `(reply, "ok")` or `(None, <failed check>)`.

    The failure code names the check only — never the reply text — so it is safe to
    log and to show in the demo console.
    """
    data = _parse_object(text)
    if data is None:
        return None, BAD_JSON

    scam_type = data.get("scam_type")
    if not isinstance(scam_type, str) or scam_type not in scam_types:
        return None, "invalid:scam_type"

    reason = data.get("reason")
    if not isinstance(reason, str) or not _reason_ok(reason.strip()):
        return None, "invalid:reason"

    line = data.get("safe_exit_line")
    if not isinstance(line, str) or not _safe_exit_ok(line.strip()):
        return None, "invalid:safe_exit_line"

    claimed_org = data.get("claimed_org")
    if claimed_org is not None and not isinstance(claimed_org, str):
        return None, "invalid:claimed_org"
    if claimed_org is not None and claimed_org not in org_ids:
        return None, "invalid:claimed_org"

    return Reply(scam_type, reason.strip(), line.strip(), claimed_org), OK
