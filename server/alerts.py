"""Turns score history into one alert level. Pure functions, no hidden state.

In: every ScorePoint recorded so far in the call.
Out: `none` / `caution` / `scam`, when the level was first reached, and why.
It does not know about transcripts, digits, the explainer, or pushes.
"""

from __future__ import annotations

import math
from typing import Sequence

from server.contracts import AlertDecision, AlertLevel, ScorePoint

# Frozen by docs/SPEC.md §2. Change the spec first, then these.
CAUTION_THRESHOLD = 0.50
SCAM_THRESHOLD = 0.85
SCAM_CONSECUTIVE = 2
SMOOTHING_WINDOW = 3

# Stable trigger ids for AlertDecision.trigger (docs/SPEC.md §4).
SCAM_TRIGGER = "two_high_chunks"
CAUTION_TRIGGER = "smoothed_risk"


def smoothed(scores: Sequence[float], window: int = SMOOTHING_WINDOW) -> list[float]:
    """Trailing mean over `window` scores, aligned to the input.

    The first `window - 1` points are means of what exists so far, so a call that
    starts loud is not diluted by imaginary zeros.
    """
    if window < 1:
        raise ValueError("smoothing window must be at least 1")
    means: list[float] = []
    for index in range(len(scores)):
        recent = scores[max(0, index - window + 1) : index + 1]
        means.append(math.fsum(recent) / len(recent))
    return means


def _first_scam_index(scores: Sequence[float]) -> int | None:
    """Index of the chunk that completes the first run of high raw scores."""
    streak = 0
    for index, score in enumerate(scores):
        streak = streak + 1 if score > SCAM_THRESHOLD else 0
        if streak >= SCAM_CONSECUTIVE:
            return index
    return None


def _caution_start(means: Sequence[float]) -> int:
    """Index where the caution stretch that reaches the latest chunk began."""
    start = len(means) - 1
    while start > 0 and means[start - 1] >= CAUTION_THRESHOLD:
        start -= 1
    return start


def decide(history: Sequence[ScorePoint]) -> AlertDecision:
    """Evaluate the whole history and return the level the call is in now.

    Rules, in order:
    - `scam` once any two consecutive raw scores are above `SCAM_THRESHOLD`, and it
      stays `scam` for the rest of the call no matter what follows.
    - `caution` while the smoothed score is at or above `CAUTION_THRESHOLD`. Caution
      is not sticky: it clears when the smoothed score falls back below.
    - `none` otherwise.

    `t_s` is the time of the chunk that first established the level, and `score` is
    the value that crossed the threshold there: the raw score for `scam`, the
    smoothed score for `caution`. For `none`, `score` is the current smoothed risk.
    Recomputing on every chunk is deliberate: `/simulate` and the live socket must
    agree exactly.
    """
    scores = [point.score for point in history]
    scam_at = _first_scam_index(scores)
    if scam_at is not None:
        point = history[scam_at]
        return AlertDecision(
            level=AlertLevel.scam, t_s=point.t_s, trigger=SCAM_TRIGGER, score=point.score
        )

    means = smoothed(scores)
    if not means:
        return AlertDecision(level=AlertLevel.none)
    if means[-1] < CAUTION_THRESHOLD:
        return AlertDecision(level=AlertLevel.none, score=means[-1])

    start = _caution_start(means)
    return AlertDecision(
        level=AlertLevel.caution,
        t_s=history[start].t_s,
        trigger=CAUTION_TRIGGER,
        score=means[start],
    )


def level_for(score: float) -> AlertLevel:
    """Display-only mapping from one raw score to a level, for the meter."""
    if score > SCAM_THRESHOLD:
        return AlertLevel.scam
    if score >= CAUTION_THRESHOLD:
        return AlertLevel.caution
    return AlertLevel.none
