"""Names the scam and finds the line to say. One model call per alert, 4 seconds.

In: the last 60 s of transcript, with every number replaced before it is sent.
Out: scam type, one-line reason, the line to say, and the claimed organisation's
verified number from server/orgs.json.
It never decides an alert, never raises, and never changes the alert level. The model
is Haiku, or Gemini when EXPLAINER_PROVIDER=gemini; every rule here is the same for both,
and for an answer the page got from its own model (`from_reply`, page_explainer.py).
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from server.config import get_settings
from server.contracts import ExplainerResult, TranscriptChunk
from server.explainer_checks import NO_ORG, OK, Reply, check_reply
from server.explainer_prompt import system_message, user_message
from server.gemini_client import GEMINI_REQUEST_OPTIONS, GeminiClient
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
GEMINI = "gemini"
# The one shape of failure detail a client may hand to the log: an HTTP status.
_LOG_CODE = re.compile(r"http_\d{3}")


def _failure_code(exc: BaseException) -> str:
    """What may be logged about a failed request: a status the client vouches for
    (`http_503`), else the exception's class name. Never its message."""
    code = getattr(exc, "log_code", None)
    if isinstance(code, str) and _LOG_CODE.fullmatch(code):
        return code
    return type(exc).__name__


def _degraded() -> ExplainerResult:
    return ExplainerResult(
        scam_type="other",
        reason=GENERIC_REASON,
        safe_exit_line=GENERIC_SAFE_EXIT,
        degraded=True,
    )


class Explainer:
    """One model call per alert, validated, degraded rather than raised.

    `client` is an `anthropic.Anthropic`-shaped object; tests pass a fake with the
    same `messages.create(...)` surface, and `GeminiClient` has it too. `orgs` lets
    tests use a small fixture. `provider` is `anthropic` or `gemini` and defaults to
    the setting; it picks the client, the model id and the optional request params,
    and nothing else. `last_code` says how the last call ended ("ok", "timeout",
    "bad_json", ...); it is a fixed code and never holds anything from the call.
    """

    def __init__(
        self,
        client: "Anthropic | GeminiClient | None" = None,
        orgs: Mapping[str, Org] | None = None,
        model: str | None = None,
        timeout_s: float = TIMEOUT_S,
        *,
        request_options: Mapping[str, Any] | None = None,
        provider: str | None = None,
    ) -> None:
        settings = get_settings()
        self._client = client
        self.orgs: dict[str, Org] = dict(orgs) if orgs is not None else load_orgs()
        self.provider = provider or settings.explainer_provider
        on_gemini = self.provider == GEMINI
        self.model = model or (settings.gemini_model if on_gemini else settings.haiku_model)
        self.timeout_s = timeout_s
        # Anthropic's params (thinking, output_config) never go to Gemini, and the reverse.
        defaults = GEMINI_REQUEST_OPTIONS if on_gemini else REQUEST_OPTIONS
        self.request_options = dict(defaults if request_options is None else request_options)
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
        return self._settle(result, code)

    def from_reply(self, text: str) -> ExplainerResult:
        """Check an answer that a model gave somewhere else, and look its org up.

        The page asks its own model through Firebase AI Logic (docs/SPEC.md §5); what
        comes back goes through every check a reply to `explain` does, and fails to
        the same generic line. It never raises and asks no model.
        """
        try:
            result, code = self._checked(text, no_org=NO_ORG)
        except Exception as exc:
            result, code = None, f"error:{type(exc).__name__}"
        return self._settle(result, code)

    def degraded(self, code: str) -> ExplainerResult:
        """The generic line, for a caller whose own model call came to nothing.

        `code` is one of the caller's fixed names (`page_timeout`), never anything from
        the call: it is logged.
        """
        return self._settle(None, code)

    def prompt_text(self, chunks: Sequence[TranscriptChunk]) -> str | None:
        """The redacted user message for `chunks`, or None when nothing was said."""
        if not any(chunk.text.strip() for chunk in chunks):
            return None
        return self._prompt(chunks)

    def page_system(self) -> str:
        """The instructions for the page's model: the same ones, except that its JSON
        schema has a word for "no organisation" where Haiku is told to say null."""
        names = {org.id: org.name for org in self.orgs.values()}
        return system_message(SCAM_TYPES, names, no_org=f'"{NO_ORG}"')

    def _settle(self, result: ExplainerResult | None, code: str) -> ExplainerResult:
        """Record how a call ended and return its result, or the generic line."""
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
        prompt = self.prompt_text(chunks)
        if prompt is None:
            return None, "empty_transcript"
        code, text = self._ask(client, prompt, deadline)
        if code != OK:
            return None, code
        return self._checked(text)

    def _checked(
        self, text: str, *, no_org: str | None = None
    ) -> tuple[ExplainerResult | None, str]:
        """Every docs/SPEC.md §5 check on a reply, whoever asked the model."""
        if not text.strip():
            return None, "empty_reply"
        reply, code = check_reply(text, SCAM_TYPES, self.orgs.keys(), no_org=no_org)
        if reply is None:
            return None, code
        return self._result(reply), OK

    def _resolve_client(self) -> "Anthropic | GeminiClient | None":
        """The provider's client, made on first use. None when its key is missing."""
        if self._client is None:
            settings = get_settings()
            if self.provider == GEMINI:
                if not settings.gemini_api_key:
                    return None
                self._client = GeminiClient(settings.gemini_api_key)
            else:
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
                box.put((f"request_failed:{_failure_code(exc)}", ""))

        threading.Thread(target=work, name="explainer-call", daemon=True).start()
        try:
            return box.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            return "timeout", ""

    def _request(self, client: Any, prompt: str) -> str:
        """One call to the model, no retries, capped at the budget. Returns the reply text."""
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
        listed = [name for org in self.orgs.values() for name in (org.name, *org.aliases)]
        return user_message(chunks, CONTEXT_S, listed)
