"""Turns score history into one alert level. Pure functions, no hidden state.

In: every ScorePoint recorded so far in the call.
Out: `none` / `caution` / `scam`, when the level was first reached, and why.
It does not know about transcripts, digits, the explainer, or pushes.
"""

from __future__ import annotations

from typing import Sequence

from server.contracts import AlertDecision, AlertLevel, ScorePoint

# Frozen by docs/SPEC.md §2. Change the spec first, then these.
CAUTION_THRESHOLD = 0.50
SCAM_THRESHOLD = 0.85
SCAM_CONSECUTIVE = 2
SMOOTHING_WINDOW = 3


def smoothed(scores: Sequence[float], window: int = SMOOTHING_WINDOW) -> list[float]:
    """Trailing mean over `window` scores, aligned to the input.

    The first `window - 1` points are means of what exists so far, so a call that
    starts loud is not diluted by imaginary zeros.
    """
    raise NotImplementedError("alert rules land in phase 4 — docs/SPEC.md §4")


def decide(history: Sequence[ScorePoint]) -> AlertDecision:
    """Evaluate the whole history and return the level the call is in now.

    Rules, in order:
    - `scam` once any two consecutive raw scores are above `SCAM_THRESHOLD`, and it
      stays `scam` for the rest of the call no matter what follows.
    - `caution` once the smoothed score reaches `CAUTION_THRESHOLD`.
    - `none` otherwise.

    `t_s` is the time of the chunk that first established the level. Recomputing on
    every chunk is deliberate: `/simulate` and the live socket must agree exactly.
    """
    raise NotImplementedError("alert rules land in phase 4 — docs/SPEC.md §4")


def level_for(score: float) -> AlertLevel:
    """Display-only mapping from one raw score to a level, for the meter."""
    if score > SCAM_THRESHOLD:
        return AlertLevel.scam
    if score >= CAUTION_THRESHOLD:
        return AlertLevel.caution
    return AlertLevel.none
