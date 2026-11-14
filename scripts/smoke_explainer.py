"""Sends one made-up scam transcript to the real Haiku API, through the real Explainer.

It prints whether the answer degraded, the reason code, the latency, and the scam type
and organisation id. It never prints the transcript or the model's sentences.
Run from the repo root once .env has ANTHROPIC_API_KEY: python scripts/smoke_explainer.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.config import get_settings  # noqa: E402
from server.contracts import TranscriptChunk  # noqa: E402
from server.explainer import Explainer  # noqa: E402

# Invented for this script: no real call, person, or card. The number is the
# standard test value, there to prove the request goes out with it redacted.
GRANDPARENT_CALL = (
    "Grandma, it's me, your grandson. I'm in trouble and I need your help.",
    "I was in a car accident and they arrested me. Please don't tell mom and dad.",
    "The lawyer says I need bail money today, and it has to be gift cards.",
    "Can you go to the store, buy them, and read me the numbers on the back?",
    "The first card is 4111 1111 1111 1111. Please hurry, they are taking my phone.",
)
CHUNK_S = 5.0
RISK = 0.95


def _chunks() -> list[TranscriptChunk]:
    return [
        TranscriptChunk(text=text, start_s=index * CHUNK_S, end_s=(index + 1) * CHUNK_S)
        for index, text in enumerate(GRANDPARENT_CALL)
    ]


def _run(label: str, explainer: Explainer, chunks: list[TranscriptChunk]) -> bool:
    """One real request. Prints codes and ids only; returns True when it did not degrade."""
    started = time.perf_counter()
    result = explainer.explain(chunks, RISK)
    latency_s = time.perf_counter() - started
    print(
        f"{label}: degraded={result.degraded} code={explainer.last_code} "
        f"latency={latency_s:.2f}s scam_type={result.scam_type} org={result.claimed_org}"
    )
    return not result.degraded


def main() -> int:
    settings = get_settings()
    print(f"model={settings.haiku_model} key={'set' if settings.has_anthropic else 'missing'}")
    chunks = _chunks()

    explainer = Explainer()
    digits_in_prompt = any(char.isdigit() for char in explainer._prompt(chunks))
    print(f"digits_in_prompt={digits_in_prompt}")
    if _run("request", explainer, chunks):
        return 0

    # If the request itself was refused, try once more with no optional params, to
    # tell "the API rejects a param" apart from "the API is unreachable".
    refused = str(explainer.last_code).startswith("request_failed")
    if refused and _run("without optional params", Explainer(request_options={}), chunks):
        print("The optional params are the problem: empty REQUEST_OPTIONS in server/explainer.py.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
