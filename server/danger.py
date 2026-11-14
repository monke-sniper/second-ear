"""Finds someone reading a number out loud, before the number is gone.

In: the call's transcript chunks, the current risk, and whether a scam alert is active.
Out: whether the code warning fires and how many digits sat inside the last 10 s.
It never returns, stores, logs, or sends the digits themselves — only a count.
"""

from __future__ import annotations

from typing import Sequence

from server.contracts import DangerDecision, TranscriptChunk
from server.explainer_prompt import NUMBER_MIN_DIGITS
from server.numbers import find_number_runs, replace_number_runs

# Frozen by docs/SPEC.md §2.
DIGIT_MIN = 6
WINDOW_S = 10.0
RISK_GATE = 0.50
# `NUMBER_MIN_DIGITS` is the 2+ digits rule: a lone "one" or "5" is ordinary speech, not
# a number being read out. Its one copy is kept with the redaction that shares it.


def normalize_spoken_numbers(text: str) -> str:
    """Rewrite spoken numbers as digits, for counting only.

    Handles the forms people actually use on a call: "four five six" → "456",
    "oh four" → "04", "double seven" → "77", "triple four" → "444", "sixteen" → "16",
    and digits that are already digits. A lone single digit ("this one", "oh,
    really") is left as it was. The result is transient — count it and drop it.
    Never log it, never put it on a decision, never send it anywhere.
    """
    return replace_number_runs(text, NUMBER_MIN_DIGITS)


def count_digits(text: str) -> int:
    """How many digits are being read out: numbers of `NUMBER_MIN_DIGITS` or more only."""
    return sum(
        run.digit_count for run in find_number_runs(text) if run.digit_count >= NUMBER_MIN_DIGITS
    )


def scan(
    chunks: Sequence[TranscriptChunk],
    risk: float,
    scam_active: bool,
    now_s: float,
) -> DangerDecision:
    """Apply the gate and count digits inside the window.

    Only chunks with `now_s - WINDOW_S < end_s <= now_s` count. Their texts are joined
    before counting, so a number split across two chunks is still one number. The
    warning fires when the count is at least `DIGIT_MIN` and (`risk > RISK_GATE` or
    `scam_active`). The count, the window and the time are returned; the digits are not.

    The case this must get right: a pharmacy reading a phone number at low risk
    does not fire. The gate, not the count, is what protects it.
    """
    in_window = " ".join(
        chunk.text for chunk in chunks if now_s - WINDOW_S < chunk.end_s <= now_s
    )
    digit_count = count_digits(in_window)
    armed = risk > RISK_GATE or scam_active
    return DangerDecision(
        fired=armed and digit_count >= DIGIT_MIN,
        digit_count=digit_count,
        window_s=WINDOW_S,
        at_s=now_s,
    )
