"""Finds someone reading a number out loud, before the number is gone.

In: the call's transcript chunks, the current risk, and whether a scam alert is active.
Out: whether the code warning fires and how many digits sat inside the last 10 s.
It never returns, stores, logs, or sends the digits themselves — only a count.
"""

from __future__ import annotations

from typing import Sequence

from server.contracts import DangerDecision, TranscriptChunk

# Frozen by docs/SPEC.md §2.
DIGIT_MIN = 6
WINDOW_S = 10.0
RISK_GATE = 0.50


def normalize_spoken_numbers(text: str) -> str:
    """Rewrite spoken numbers as digits, for counting only.

    Handles the forms people actually use on a call: "four five six" → "456",
    "oh" → "0", "double seven" → "77", "triple four" → "444", "sixteen" → "16",
    and digits that are already digits. The result is transient — count it and
    drop it. Never log it, never put it on a decision, never send it anywhere.
    """
    raise NotImplementedError("digit rules land in phase 4 — docs/SPEC.md §4")


def scan(
    chunks: Sequence[TranscriptChunk],
    risk: float,
    scam_active: bool,
    now_s: float,
) -> DangerDecision:
    """Apply the gate and count digits inside the window.

    Only chunks with `now_s - WINDOW_S < end_s <= now_s` count. The warning fires
    when the count is at least `DIGIT_MIN` and (`risk > RISK_GATE` or `scam_active`).
    The count, the window and the time are returned; the digits are not.

    The case this must get right: a pharmacy reading a phone number at low risk
    does not fire. The gate, not the count, is what protects it.
    """
    raise NotImplementedError("digit rules land in phase 4 — docs/SPEC.md §4")
