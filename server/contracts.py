"""Every message that crosses the WebSocket or the HTTP surface.

This module is the single source of truth for wire shapes: the server, the browser
client and the tests all speak these models. It implements no behaviour — nothing
here decides, scores, or sends; those live in the modules named by the spec.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

# Audio contract (docs/SPEC.md §2). 16 kHz mono signed 16-bit little-endian.
SAMPLE_RATE = 16_000
SAMPLE_WIDTH_BYTES = 2
FRAME_MS = 250
FRAME_BYTES = SAMPLE_RATE * SAMPLE_WIDTH_BYTES * FRAME_MS // 1000  # 8_000
MAX_FRAME_BYTES = 64 * 1024


class WireModel(BaseModel):
    """Base for every message. Unknown fields are a bug, not a feature."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AlertLevel(str, Enum):
    none = "none"
    caution = "caution"
    scam = "scam"


# --------------------------------------------------------------------------- audio


class TranscriptChunk(WireModel):
    """One transcribed audio chunk. `start_s`/`end_s` are seconds into the call."""

    text: str
    start_s: float
    end_s: float
    language: str | None = None

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


class ScorePoint(WireModel):
    """One model score at one moment of the call."""

    t_s: float
    score: float = Field(ge=0.0, le=1.0)


# ------------------------------------------------------------------ module results


class AlertDecision(WireModel):
    """What the alert rules say about the call so far.

    `t_s` is when the level was first reached; `None` while the level is `none`.
    `trigger` is a short stable id (`two_high_chunks`, `risk_softened`), never prose.
    """

    level: AlertLevel
    t_s: float | None = None
    trigger: str | None = None
    score: float = Field(default=0.0, ge=0.0, le=1.0)


class DangerDecision(WireModel):
    """The code-warning verdict. Deliberately carries no digits, ever."""

    fired: bool
    digit_count: int = Field(ge=0)
    window_s: float = Field(gt=0.0)
    at_s: float


class ExplainerResult(WireModel):
    """Haiku's read of the call, after validation and org lookup.

    `degraded=True` means the model timed out or produced something unusable and
    `safe_exit_line` is the generic line. The alert level is unaffected either way.
    """

    scam_type: str
    reason: str
    safe_exit_line: str
    claimed_org: str | None = None
    org_name: str | None = None
    official_number: str | None = None
    degraded: bool = False


# ------------------------------------------------------------------- server events


class AudioAck(WireModel):
    """Phase 1 proof of life: the socket received bytes and counted them."""

    type: Literal["ack"] = "ack"
    bytes: int
    total: int


class TranscriptEvent(WireModel):
    """One chunk's text, final. The client appends it to the running transcript."""

    type: Literal["transcript"] = "transcript"
    text: str
    t_s: float


class RiskEvent(WireModel):
    """The current risk and the level the rules derive from it."""

    type: Literal["risk"] = "risk"
    score: float = Field(ge=0.0, le=1.0)
    t_s: float
    level: AlertLevel = AlertLevel.none


class AlertEvent(WireModel):
    """Fires the moment the rules escalate; the sheet must not wait for the explainer."""

    type: Literal["alert"] = "alert"
    level: AlertLevel
    t_s: float
    trigger: str
    score: float = Field(ge=0.0, le=1.0)


class ExplainerEvent(WireModel):
    """Late enrichment for an open alert: scam name, line to say, callback number."""

    type: Literal["explainer"] = "explainer"
    t_s: float
    scam_type: str
    reason: str
    safe_exit_line: str
    org: str | None = None
    org_name: str | None = None
    official_number: str | None = None
    degraded: bool = False


class DangerEvent(WireModel):
    """The code warning. A count, never the digits."""

    type: Literal["danger"] = "danger"
    digit_count: int = Field(ge=0)
    t_s: float


class ExplainRequest(WireModel):
    """Asks the page to make the explainer's model call, through Firebase AI Logic.

    Sent after an alert, only when Firebase is set up. `prompt` is the last minute of
    the call with every number already replaced; `id` comes back on the answer.
    """

    type: Literal["explain"] = "explain"
    id: int = Field(ge=0)
    t_s: float
    prompt: str


class ErrorEvent(WireModel):
    type: Literal["error"] = "error"
    detail: str


ServerEvent = Annotated[
    Union[
        AudioAck,
        TranscriptEvent,
        RiskEvent,
        AlertEvent,
        ExplainerEvent,
        DangerEvent,
        ExplainRequest,
        ErrorEvent,
    ],
    Field(discriminator="type"),
]


# ------------------------------------------------------------------- client events

# Room for one short JSON answer and no more. The explainer asks for about 300 characters.
MAX_REPLY_CHARS = 4_000


class PageAnswer(WireModel):
    """The page's answer to an `explain` request: the model's raw text, unchecked.

    `source` is where the model ran: `on_device` (Gemini Nano in Chrome), `in_cloud`
    (cloud Gemini), or `none` with an empty `text` when the page could not ask one.
    """

    type: Literal["explained"] = "explained"
    id: int = Field(ge=0)
    text: str = Field(max_length=MAX_REPLY_CHARS)
    source: Literal["on_device", "in_cloud", "none"]


# ---------------------------------------------------------------------- HTTP shapes


class SimulateRequest(WireModel):
    """Replay text chunks through the real pipeline, no audio and no mic."""

    chunks: list[str] = Field(min_length=1)
    chunk_seconds: float = Field(default=4.0, gt=0.0, le=30.0)


class TimelinePoint(WireModel):
    t_s: float
    score: float = Field(ge=0.0, le=1.0)
    level: AlertLevel


class SimulateResponse(WireModel):
    timeline: list[TimelinePoint]
    alerts: list[AlertEvent]
    explainers: list[ExplainerEvent]
    danger: list[DangerEvent]


class PageExplainerConfig(WireModel):
    """What `GET /explainer/config` tells the page. Without Firebase it is `enabled`
    alone, and the page loads no SDK and is never asked to explain.

    `firebase` is passed to the SDK's `initializeApp` as it is, so its keys are
    Firebase's own (`apiKey`, `projectId`, `appId`).
    """

    enabled: bool
    firebase: dict[str, str] | None = None
    model: str | None = None
    system: str | None = None
    reply_schema: dict[str, Any] | None = None
