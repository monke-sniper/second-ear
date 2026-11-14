"""Names the scam and finds the line to say. One Haiku call per alert, 4 seconds.

In: the last 60 s of transcript, with every digit run replaced before it is sent.
Out: scam type, one-line reason, the line to say, and the claimed organisation's
verified number from server/orgs.json.
It never decides an alert, never raises, and never changes the alert level.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from server.config import get_settings
from server.contracts import ExplainerResult, TranscriptChunk

if TYPE_CHECKING:  # import only for type checkers; the SDK is loaded lazily at runtime
    from anthropic import Anthropic

# Frozen by docs/SPEC.md §5.
GENERIC_SAFE_EXIT = "I'll call you back at the number on my card."
TIMEOUT_S = 4.0
CONTEXT_S = 60.0
SCAM_TYPES = (
    "grandparent",
    "medicare",
    "ssn",
    "refund",
    "tech_support",
    "gift_card",
    "reward",
    "romance",
    "bank_fraud",
    "other",
)


@dataclass(frozen=True)
class Org:
    """One entry from orgs.json. `phone` is None until it is verified on the site."""

    id: str
    name: str
    phone: str | None
    aliases: tuple[str, ...]
    source_url: str | None = None
    verified_at: str | None = None


def load_orgs(path: Path | None = None) -> dict[str, Org]:
    """Read orgs.json into `{id: Org}`. The file ships with phones unset on purpose."""
    target = Path(path or get_settings().orgs_path)
    raw = json.loads(target.read_text(encoding="utf-8"))
    orgs: dict[str, Org] = {}
    for entry in raw["orgs"]:
        org = Org(
            id=entry["id"],
            name=entry["name"],
            phone=entry.get("phone"),
            aliases=tuple(entry.get("aliases", ())),
            source_url=entry.get("source_url"),
            verified_at=entry.get("verified_at"),
        )
        orgs[org.id] = org
    return orgs


def redact_digits(text: str, min_run: int = 6) -> str:
    """Replace every run of `min_run` or more digits with `[number]`.

    This is the only transformation allowed between the transcript and the Haiku
    request. Nothing longer than five digits survives it either way, so a card
    number, a gift-card code, and an SSN can never reach the model.
    """
    raise NotImplementedError("explainer lands in phase 4 — docs/SPEC.md §5")


class Explainer:
    """One Haiku call per alert, validated, degraded rather than raised.

    `client` is an `anthropic.Anthropic`-shaped object; tests pass a fake with the
    same `messages.create(...)` surface. `orgs` lets tests use a small fixture.
    """

    def __init__(
        self,
        client: "Anthropic | None" = None,
        orgs: Mapping[str, Org] | None = None,
        model: str | None = None,
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        self._client = client
        self.orgs: dict[str, Org] = dict(orgs) if orgs is not None else load_orgs()
        self.model = model or get_settings().haiku_model
        self.timeout_s = timeout_s

    def explain(self, chunks: Sequence[TranscriptChunk], risk: float) -> ExplainerResult:
        """Return the safest useful read of the call, or the generic line.

        Builds the prompt from the last `CONTEXT_S` seconds, redacted; asks for JSON
        only; validates every field against docs/SPEC.md §5; looks the claimed org up
        in `self.orgs`. Any failure returns `degraded=True` with the generic line —
        the alert itself is never weakened or withdrawn.
        """
        raise NotImplementedError("explainer lands in phase 4 — docs/SPEC.md §5")

    def _prompt(self, chunks: Sequence[TranscriptChunk]) -> str:
        """The exact user message. Kept as its own method so a test can assert the
        prompt contains no digit run."""
        raise NotImplementedError("explainer lands in phase 4 — docs/SPEC.md §5")
