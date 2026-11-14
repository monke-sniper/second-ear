"""Names the scam and finds the line to say. One Haiku call per alert, 4 seconds.

In: the last 60 s of transcript, with every number replaced before it is sent.
Out: scam type, one-line reason, the line to say, and the claimed organisation's
verified number from server/orgs.json.
It never decides an alert, never raises, and never changes the alert level.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from server.config import get_settings
from server.contracts import ExplainerResult, TranscriptChunk
from server.explainer_checks import OK, Reply, check_reply
from server.explainer_prompt import REDACTED, system_message, user_message
from server.numbers import replace_number_runs
from server.orgs import Org, load_orgs  # also imported from here by tests and callers

if TYPE_CHECKING:  # import only for type checkers; the SDK is loaded lazily at runtime
    from anthropic import Anthropic

log = logging.getLogger("second_ear.explainer")

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
GENERIC_REASON = "The call sounds like a scam."

# Not in SPEC: room for one short JSON answer inside a 4 s budget.
MAX_TOKENS = 256
# Optional request params. scripts/smoke_explainer.py tells you if the API refuses
# them; if it does, delete the entry rather than work around it.
REQUEST_OPTIONS: Mapping[str, Any] = {
    "thinking": {"type": "disabled"},
    "output_config": {"effort": "low"},
}


def redact_digits(text: str, min_run: int = 6) -> str:
    """Replace every number of `min_run` or more digits with `[number]`.

    Spoken and written numbers are treated alike ("four five six seven eight nine",
    "4111 1111", "123-45-6789"), and spaces, commas, dots and hyphens do not break a
    number. The prompt itself is redacted harder than this default, at two digits:
    see `explainer_prompt.redact_for_prompt`.
    """
    return replace_number_runs(text, min_run, REDACTED)


def _degraded() -> ExplainerResult:
    return ExplainerResult(
        scam_type="other",
        reason=GENERIC_REASON,
        safe_exit_line=GENERIC_SAFE_EXIT,
        degraded=True,
    )


class Explainer:
    """One Haiku call per alert, validated, degraded rather than raised.

    `client` is an `anthropic.Anthropic`-shaped object; tests pass a fake with the
    same `messages.create(...)` surface. `orgs` lets tests use a small fixture.
    `last_code` says how the last call ended ("ok", "timeout", "bad_json", ...); it
    is a fixed code and never holds anything from the call.
    """

    def __init__(
        self,
        client: "Anthropic | None" = None,
        orgs: Mapping[str, Org] | None = None,
        model: str | None = None,
        timeout_s: float = TIMEOUT_S,
        *,
        request_options: Mapping[str, Any] | None = None,
    ) -> None:
        self._client = client
        self.orgs: dict[str, Org] = dict(orgs) if orgs is not None else load_orgs()
        self.model = model or get_settings().haiku_model
        self.timeout_s = timeout_s
        options = REQUEST_OPTIONS if request_options is None else request_options
        self.request_options = dict(options)
        self.last_code: str | None = None

    def explain(self, chunks: Sequence[TranscriptChunk], risk: float) -> ExplainerResult:
        """Return the safest useful read of the call, or the generic line.

        Builds the prompt from the last `CONTEXT_S` seconds, redacted; asks for JSON
        only; validates every field against docs/SPEC.md §5; looks the claimed org up
        in `self.orgs`. Any failure returns `degraded=True` with the generic line —
        the alert itself is never weakened or withdrawn. The whole call, slow model
        included, returns within `timeout_s`. `risk` is part of the contract but the
        explainer never acts on it: it cannot decide or change an alert.
        """
        deadline = time.monotonic() + self.timeout_s
        try:
            result, code = self._explain(chunks, deadline)
        except Exception as exc:  # never raise: the alert must stand
            result, code = None, f"error:{type(exc).__name__}"
        self.last_code = code
        if result is None:
            # The code and a class name only. Never the transcript, the reply, or an
            # exception message: any of them could carry what was said on the call.
            log.warning("explainer degraded: %s", code)
            return _degraded()
        return result

    def _explain(
        self, chunks: Sequence[TranscriptChunk], deadline: float
    ) -> tuple[ExplainerResult | None, str]:
        client = self._resolve_client()
        if client is None:
            return None, "no_api_key"
        if not any(chunk.text.strip() for chunk in chunks):
            return None, "empty_transcript"
        code, text = self._ask(client, self._prompt(chunks), deadline)
        if code != OK:
            return None, code
        if not text.strip():
            return None, "empty_reply"
        reply, code = check_reply(text, SCAM_TYPES, self.orgs.keys())
        if reply is None:
            return None, code
        return self._result(reply), OK

    def _resolve_client(self) -> "Anthropic | None":
        if self._client is None:
            settings = get_settings()
            if not settings.has_anthropic:
                return None
            from anthropic import Anthropic

            self._client = Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def _ask(self, client: Any, prompt: str, deadline: float) -> tuple[str, str]:
        """Run the request in a daemon thread and wait only until `deadline`.

        A hung request is abandoned, not joined: the thread ends when the SDK's own
        timeout fires, and being a daemon it never holds up shutdown.
        """
        box: queue.SimpleQueue[tuple[str, str]] = queue.SimpleQueue()

        def work() -> None:
            try:
                box.put((OK, self._request(client, prompt)))
            except BaseException as exc:  # a dying thread would print the message
                box.put((f"request_failed:{type(exc).__name__}", ""))

        threading.Thread(target=work, name="explainer-call", daemon=True).start()
        try:
            return box.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            return "timeout", ""

    def _request(self, client: Any, prompt: str) -> str:
        """One Messages call, no retries, capped at the budget. Returns the reply text."""
        with_options = getattr(client, "with_options", None)
        if callable(with_options):
            client = with_options(timeout=self.timeout_s, max_retries=0)
        response = client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=self._system(),
            messages=[{"role": "user", "content": prompt}],
            **self.request_options,
        )
        texts: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)  # by attribute: thinking blocks have none
            if isinstance(text, str):
                texts.append(text)
        return "".join(texts)

    def _result(self, reply: Reply) -> ExplainerResult:
        org = self.orgs.get(reply.claimed_org) if reply.claimed_org else None
        return ExplainerResult(
            scam_type=reply.scam_type,
            reason=reply.reason,
            safe_exit_line=reply.safe_exit_line,
            claimed_org=reply.claimed_org,
            org_name=org.name if org is not None else None,
            # Shown only when it was checked on the organisation's own site.
            official_number=org.verified_phone if org is not None else None,
        )

    def _system(self) -> str:
        return system_message(SCAM_TYPES, {org.id: org.name for org in self.orgs.values()})

    def _prompt(self, chunks: Sequence[TranscriptChunk]) -> str:
        """The exact user message. Kept as its own method so a test can assert the
        prompt contains no digit run."""
        return user_message(chunks, CONTEXT_S)
