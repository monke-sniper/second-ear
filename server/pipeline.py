"""One call's state, and what each transcribed chunk turns into.

In: a chunk's text and how long it lasted. Out: the transcript, risk, alert and danger
events for that chunk, in send order. The socket and /simulate both run this.
It does not touch audio, sockets, Whisper, or pushes, and it never logs what was said.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from server import alerts, danger
from server.contracts import (
    AlertDecision,
    AlertEvent,
    AlertLevel,
    DangerEvent,
    ExplainerEvent,
    ExplainerResult,
    RiskEvent,
    ScorePoint,
    SimulateRequest,
    SimulateResponse,
    TimelinePoint,
    TranscriptChunk,
    TranscriptEvent,
    WireModel,
)
from server.explainer import Explainer
from server.explainer_prompt import redact_outbound
from server.scorer import RiskScorer

log = logging.getLogger("second_ear.pipeline")

_RANK = {AlertLevel.none: 0, AlertLevel.caution: 1, AlertLevel.scam: 2}


@dataclass(frozen=True)
class Step:
    """What one chunk produced. Every field is None for a silent chunk."""

    transcript: TranscriptEvent | None = None
    risk: RiskEvent | None = None
    alert: AlertEvent | None = None
    danger: DangerEvent | None = None

    @property
    def events(self) -> tuple[WireModel, ...]:
        """The events in the order they go out: the alert never waits on anything."""
        ordered = (self.transcript, self.risk, self.alert, self.danger)
        return tuple(event for event in ordered if event is not None)


class CallSession:
    """Per-call state: the clock, the transcript, the scores, and what was already sent.

    `alerts.decide` stays a pure function; this class is what remembers the highest
    level already announced, so an alert goes out only when the level rises (none →
    caution → scam) and never when it falls back. `generation` counts resets: work
    started for an earlier call can tell that its answer is late. `outranked` says the
    same about an answer for an alert that a higher one has since replaced.
    """

    def __init__(self, scorer: RiskScorer) -> None:
        self.scorer = scorer
        self.generation = 0
        self.now_s = 0.0
        self._chunks: list[TranscriptChunk] = []
        self._history: list[ScorePoint] = []
        self._announced = AlertLevel.none
        self._danger_sent = False

    @property
    def chunks(self) -> tuple[TranscriptChunk, ...]:
        """A snapshot of the transcript so far, safe to hand to another thread."""
        return tuple(self._chunks)

    @property
    def history(self) -> tuple[ScorePoint, ...]:
        return tuple(self._history)

    def outranked(self, level: AlertLevel) -> bool:
        """True when an alert above `level` has already gone out in this call.

        An explainer answer for `level` is then stale: the screen shows the higher
        alert, and the older answer was written from less of the call.
        """
        return _RANK[level] < _RANK[self._announced]

    def reset(self) -> None:
        """A new call: empty transcript, no scores, no alert state, clock at zero."""
        self.generation += 1
        self.now_s = 0.0
        self._chunks = []
        self._history = []
        self._announced = AlertLevel.none
        self._danger_sent = False

    def ingest(self, text: str, duration_s: float) -> Step:
        """Take one chunk and return its events.

        A silent or empty chunk only moves the clock: no transcript, no score point,
        no risk event. Otherwise the running transcript is scored, the alert rules
        run over the whole history, and the digit gate uses this chunk's raw score.
        """
        start_s = self.now_s
        self.now_s = start_s + duration_s
        spoken = text.strip()
        if not spoken:
            return Step()

        self._chunks.append(TranscriptChunk(text=spoken, start_s=start_s, end_s=self.now_s))
        score = self._score()
        self._history.append(ScorePoint(t_s=self.now_s, score=score))
        decision = alerts.decide(self._history)
        return Step(
            # On the wire a number is "[number]"; the raw text stays in memory only.
            transcript=TranscriptEvent(text=redact_outbound(spoken), t_s=self.now_s),
            risk=RiskEvent(score=score, t_s=self.now_s, level=decision.level),
            alert=self._rising_alert(decision),
            danger=self._danger_once(score, decision.level is AlertLevel.scam),
        )

    def _score(self) -> float:
        """Score the transcript so far. A broken scorer scores 0.0; the call goes on."""
        transcript = " ".join(chunk.text for chunk in self._chunks)
        try:
            value = float(self.scorer.score(transcript))
        except Exception as exc:
            log.warning("scorer failed: %s", type(exc).__name__)
            return 0.0
        if not math.isfinite(value):
            return 0.0
        return min(1.0, max(0.0, value))

    def _rising_alert(self, decision: AlertDecision) -> AlertEvent | None:
        if _RANK[decision.level] <= _RANK[self._announced]:
            return None
        self._announced = decision.level
        return AlertEvent(
            level=decision.level,
            t_s=decision.t_s if decision.t_s is not None else self.now_s,
            trigger=decision.trigger or "",
            score=decision.score,
        )

    def _danger_once(self, raw_score: float, scam_active: bool) -> DangerEvent | None:
        if self._danger_sent:
            return None
        verdict = danger.scan(self._chunks, raw_score, scam_active, self.now_s)
        if not verdict.fired:
            return None
        self._danger_sent = True
        return DangerEvent(digit_count=verdict.digit_count, t_s=self.now_s)


def explainer_event(result: ExplainerResult, t_s: float) -> ExplainerEvent:
    """The wire form of an explainer result, stamped with its alert's time."""
    return ExplainerEvent(
        t_s=t_s,
        scam_type=result.scam_type,
        reason=result.reason,
        safe_exit_line=result.safe_exit_line,
        org=result.claimed_org,
        org_name=result.org_name,
        official_number=result.official_number,
        degraded=result.degraded,
    )


def simulate(request: SimulateRequest, scorer: RiskScorer, explainer: Explainer) -> SimulateResponse:
    """Replay text chunks through a fresh session, as the socket would.

    The explainer runs once per alert. There is no notifier here: a replay never
    sends a push.
    """
    session = CallSession(scorer)
    timeline: list[TimelinePoint] = []
    alert_events: list[AlertEvent] = []
    explainers: list[ExplainerEvent] = []
    danger_events: list[DangerEvent] = []
    for text in request.chunks:
        step = session.ingest(text, request.chunk_seconds)
        if step.risk is not None:
            risk = step.risk
            timeline.append(TimelinePoint(t_s=risk.t_s, score=risk.score, level=risk.level))
        if step.alert is not None:
            alert_events.append(step.alert)
            result = explainer.explain(session.chunks, step.alert.score)
            explainers.append(explainer_event(result, step.alert.t_s))
        if step.danger is not None:
            danger_events.append(step.danger)
    return SimulateResponse(
        timeline=timeline, alerts=alert_events, explainers=explainers, danger=danger_events
    )
