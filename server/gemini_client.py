"""A Gemini client with the one method the Explainer calls.

In: the same `messages.create(model=, max_tokens=, system=, messages=)` call the Anthropic
SDK takes. Out: an object with `.content[0].text`, from Gemini's generateContent over httpx.
It sends one request and never retries. It does not redact, validate, time the budget or
decide anything: the Explainer does all of that around it, the same for either provider.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import httpx

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
KEY_HEADER = "x-goog-api-key"  # the key travels in a header, never in the URL
DEFAULT_TIMEOUT_S = 4.0
JSON_MIME = "application/json"
# Anthropic says "assistant" where Gemini says "model".
_ROLES = {"user": "user", "assistant": "model"}
# Optional request params, passed by the Explainer as keyword arguments. Minimal thinking
# keeps the answer inside the 4 s budget: on Nov 14 gemini-3.6-flash took 2.5 s with its
# default thinking and 1.3 s with this. scripts/smoke_explainer.py tells you if the API
# refuses it; if it does, empty this mapping rather than work around it.
GEMINI_REQUEST_OPTIONS: Mapping[str, Any] = {
    "generation_config": {"thinkingConfig": {"thinkingLevel": "MINIMAL"}},
}


class GeminiStatusError(RuntimeError):
    """Gemini answered with an HTTP error. Holds the status code and nothing else.

    `log_code` is the only thing about the failure that may be logged: the body of an
    error answer is never read, so nothing it echoes back can reach a log line.
    """

    def __init__(self, status_code: int) -> None:
        super().__init__(f"Gemini answered {status_code}")
        self.status_code = status_code
        self.log_code = f"http_{status_code}"


def _reply_text(answer: Any) -> str:
    """The text of the first candidate, without thought parts. Anything else is empty."""
    try:
        parts = answer["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts if not part.get("thought"))
    except (KeyError, IndexError, TypeError, AttributeError):
        return ""


class GeminiClient:
    """Talks to generateContent with the Anthropic client's shape.

    `messages.create(...)` returns `.content`, a list with one block that has `.text`.
    A status other than 200 raises `GeminiStatusError`; a timeout raises httpx's own
    error. Either way the Explainer degrades: a 503 or 429 is not retried here, because
    a retry would not fit in the 4 s the person has. `http` lets tests pass a client
    with a mock transport.
    """

    def __init__(
        self, api_key: str, *, timeout_s: float = DEFAULT_TIMEOUT_S, http: httpx.Client | None = None
    ) -> None:
        self._key = api_key
        self._timeout_s = timeout_s
        self._http = http if http is not None else httpx.Client()
        self.messages = SimpleNamespace(create=self._create)

    def with_options(self, *, timeout: float | None = None, max_retries: int = 0) -> "GeminiClient":
        """The same client with another time limit. There are no retries to configure."""
        limit = self._timeout_s if timeout is None else timeout
        return GeminiClient(self._key, timeout_s=limit, http=self._http)

    def _create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: Sequence[Mapping[str, str]],
        generation_config: Mapping[str, Any] | None = None,
    ) -> SimpleNamespace:
        """One generateContent request, JSON asked for. Returns the reply as a text block.

        `max_tokens` is part of the shared surface and is not sent. Gemini counts its
        thinking against the output cap, so a cap sized for the answer cuts the JSON off
        whenever thinking is not minimal (seen on Nov 14: `bad_json` at a cap of 256).
        The reply is bounded by the 4 s deadline and by validation instead.
        """
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {"role": _ROLES[message["role"]], "parts": [{"text": message["content"]}]}
                for message in messages
            ],
            "generationConfig": {"responseMimeType": JSON_MIME, **(generation_config or {})},
        }
        response = self._http.post(
            f"{API_BASE}/models/{model}:generateContent",
            headers={KEY_HEADER: self._key},
            json=body,
            timeout=self._timeout_s,
        )
        if response.status_code != 200:
            raise GeminiStatusError(response.status_code)
        try:
            answer = response.json()
        except ValueError:
            answer = None
        return SimpleNamespace(content=[SimpleNamespace(text=_reply_text(answer))])
