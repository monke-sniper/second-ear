"""The explainer's model call, made by the page through Firebase AI Logic.

In: the server's Firebase settings, and the page's `explained` message.
Out: what the page needs to make the call (config, instructions, a JSON schema for the
answer), and the page's answer as plain values, handed to the request waiting for it.
It calls no model and checks no answer: the page asks Gemini Nano on the device, or
cloud Gemini when Chrome has none, and explainer.py validates what comes back.
"""

from __future__ import annotations

import asyncio
from typing import Any, Iterable, Sequence

from pydantic import ValidationError

from server.config import FirebaseSettings
from server.contracts import PageAnswer, PageExplainerConfig
from server.explainer import SCAM_TYPES, Explainer
from server.explainer_checks import NO_ORG

# Fixed names for the ways the page's call comes to nothing. They are logged, so none
# of them may ever hold anything from the call.
PAGE_TIMEOUT = "page_timeout"  # the budget ran out before the page answered
PAGE_GONE = "page_gone"  # the call was reset, or the page left, while it was asked
PAGE_NO_ANSWER = "page_no_answer"  # the page said it could not ask a model


def reply_schema(scam_types: Sequence[str], org_ids: Iterable[str]) -> dict[str, Any]:
    """The JSON schema the page hands to its model, in the cloud and on the device.

    It narrows what the model can write; it replaces no check. `claimed_org` has a word
    for "no organisation" because a schema cannot say null on every model.
    """
    return {
        "type": "object",
        "properties": {
            "scam_type": {"type": "string", "enum": [*scam_types]},
            "reason": {"type": "string"},
            "safe_exit_line": {"type": "string"},
            "claimed_org": {"type": "string", "enum": [*org_ids, NO_ORG]},
        },
        "required": ["scam_type", "reason", "safe_exit_line", "claimed_org"],
    }


def page_config(firebase: FirebaseSettings | None, explainer: Explainer) -> PageExplainerConfig:
    """What the page is told at load. Without Firebase: that the call is not its job."""
    if firebase is None:
        return PageExplainerConfig(enabled=False)
    return PageExplainerConfig(
        enabled=True,
        firebase={
            "apiKey": firebase.api_key,
            "projectId": firebase.project_id,
            "appId": firebase.app_id,
        },
        model=firebase.model,
        system=explainer.page_system(),
        reply_schema=reply_schema(SCAM_TYPES, explainer.orgs.keys()),
    )


def parse_explained(text: str) -> PageAnswer | None:
    """The page's `explained` message, or None when it is not exactly that shape.

    Strict: an id that is a string or a bool, a source outside the fixed three, an extra
    field or an over-long text is refused. Nothing from a refused message is kept.
    """
    try:
        return PageAnswer.model_validate_json(text, strict=True)
    except ValidationError:
        return None


class PageDesk:
    """The answers one connection is waiting for from its page, by request id.

    `expect()` starts a request, `settle()` hands it the page's answer, `close()` ends it
    whether or not an answer came. `abandon()` ends every open request with None in
    place of an answer: the call was reset, or the page has gone. It lives on the
    socket's event loop and is not safe to use from another thread.
    """

    def __init__(self) -> None:
        self._next_id = 0
        self._waiting: dict[int, asyncio.Future[PageAnswer | None]] = {}

    def expect(self) -> tuple[int, asyncio.Future[PageAnswer | None]]:
        """A new request id, and the future its answer will arrive on."""
        request_id = self._next_id
        self._next_id += 1
        answer: asyncio.Future[PageAnswer | None] = asyncio.get_running_loop().create_future()
        self._waiting[request_id] = answer
        return request_id, answer

    def settle(self, answer: PageAnswer) -> bool:
        """Hand `answer` to its request. False when nobody is waiting for it: the id is
        unknown, the request ran out of time, or it was already answered."""
        waiting = self._waiting.get(answer.id)
        if waiting is None or waiting.done():
            return False
        waiting.set_result(answer)
        return True

    def close(self, request_id: int) -> None:
        self._waiting.pop(request_id, None)

    def abandon(self) -> None:
        """End every open request now. Each one is told there will be no answer."""
        for waiting in self._waiting.values():
            if not waiting.done():
                waiting.set_result(None)
        self._waiting = {}
