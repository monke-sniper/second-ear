"""Writes the held-out test set by asking Gemini, a different model than the training data's.

In: the brief and the 100 slots from eval/heldout_brief.py, and GEMINI_API_KEY from .env.
Out: eval/heldout/gemini.jsonl (one call per row) and gemini.meta.json (how it was made).
It checks format only, never scores a transcript, never drops one for being easy or hard,
and refuses to overwrite a set that already exists. Run: python -m eval.make_heldout
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import httpx

from eval.heldout_brief import BRIEF, SCENARIOS, Scenario, Slot, batch_request, build_plan, spec_sha256
from eval.heldout_checks import CHECKS, clean, format_problem
from eval.metrics import utc_now, write_json
from server.config import ROOT, get_settings
from server.gemini_client import API_BASE, KEY_HEADER  # one endpoint, one key header

TIMEOUT_S = 240.0
RETRY_STATUS = frozenset({429, 500, 503})
HTTP_TRIES = 5
RETRY_WAIT_S = 20.0
# A transcript that fails a format check is asked for again, this many rounds in all.
ITEM_ROUNDS = 3
DEFAULT_OUT = ROOT / "eval" / "heldout" / "gemini.jsonl"
META_SCHEMA = "second-ear/heldout-v1"


class GeminiError(RuntimeError):
    """The generator could not finish. The message never holds the key or a transcript."""


def request_body(scenario: Scenario, slots: list[Slot]) -> dict[str, Any]:
    """One generateContent request: the brief as system text, one kind of call, JSON out."""
    item = {"type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}}, "required": ["id", "text"]}
    schema = {
        "type": "object",
        "properties": {"transcripts": {"type": "array", "items": item, "minItems": len(slots), "maxItems": len(slots)}},
        "required": ["transcripts"],
    }
    return {
        "systemInstruction": {"parts": [{"text": BRIEF}]},
        "contents": [{"role": "user", "parts": [{"text": batch_request(scenario, slots)}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": schema},
    }


def _error_text(response: httpx.Response, key: str) -> str:
    try:
        message = str(response.json()["error"]["message"])
    except (ValueError, KeyError, TypeError):
        message = "no error message"
    return message.replace(key, "[key]")[:300]


def post(client: httpx.Client, model: str, key: str, body: dict, sleep: Callable[[float], None]) -> dict:
    """Send one request. A busy or rate-limited answer is retried after a wait."""
    url = f"{API_BASE}/models/{model}:generateContent"
    for attempt in range(1, HTTP_TRIES + 1):
        response = client.post(url, headers={KEY_HEADER: key}, json=body)
        if response.status_code == 200:
            return response.json()
        if response.status_code not in RETRY_STATUS or attempt == HTTP_TRIES:
            raise GeminiError(f"Gemini answered {response.status_code}: {_error_text(response, key)}")
        sleep(RETRY_WAIT_S * attempt)
    raise GeminiError("Gemini did not answer")  # unreachable; keeps the return type honest


def transcripts_in(answer: dict) -> dict[str, str]:
    """`id -> cleaned text` from one answer. An unreadable answer gives an empty dict."""
    try:
        parts = answer["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        items = json.loads(text.strip().removeprefix("```json").removesuffix("```"))["transcripts"]
        return {str(item["id"]): clean(item.get("text")) for item in items}
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return {}


def generate(client: httpx.Client, model: str, key: str, sleep: Callable[[float], None] = time.sleep) -> tuple[list[dict], dict]:
    """Fill every slot. Returns the rows in plan order and the facts about the run."""
    plan = build_plan()
    texts: dict[str, str] = {}
    requests, extra_rounds, versions = 0, 0, set()
    for scenario in SCENARIOS:
        pending = [slot for slot in plan if slot.type == scenario.type]
        problems: dict[str, str] = {}
        for round_number in range(1, ITEM_ROUNDS + 1):
            answer = post(client, model, key, request_body(scenario, pending), sleep)
            requests += 1
            extra_rounds += round_number > 1
            versions.add(str(answer.get("modelVersion") or ""))
            got = transcripts_in(answer)
            problems = {slot.id: format_problem(slot, got.get(slot.id, "")) for slot in pending}
            texts.update({slot.id: got[slot.id] for slot in pending if problems[slot.id] is None})
            pending = [slot for slot in pending if problems[slot.id] is not None]
            if not pending:
                break
        if pending:
            reasons = sorted({str(problems[slot.id]) for slot in pending})
            raise GeminiError(f"{scenario.type}: {len(pending)} transcript(s) still fail the format checks ({', '.join(reasons)})")
    rows = [{"id": s.id, "label": s.label, "type": s.type, "opening": s.opening, "text": texts[s.id]} for s in plan]
    openings = {name: dict(Counter(r["opening"] for r in rows if r["label"] == label)) for name, label in (("scam", 1), ("legitimate", 0))}
    meta = {
        "schema": META_SCHEMA,
        "created_utc": utc_now(),
        "generator": {"api": f"{API_BASE}/models/{{model}}:generateContent", "model": model, "model_versions": sorted(v for v in versions if v)},
        "brief_sha256": spec_sha256(),
        "rows": len(rows),
        "labels": {"scam": sum(r["label"] for r in rows), "legitimate": sum(1 - r["label"] for r in rows)},
        "by_type": dict(Counter(r["type"] for r in rows)),
        "openings": openings,
        "requests": requests,
        "extra_rounds": extra_rounds,
        "format_checks": list(CHECKS),
        "whitespace": "collapsed",
        "selection": "none: every transcript that passed the format checks is in the file; no scorer ran",
    }
    return rows, meta


def check(client: httpx.Client, model: str, key: str) -> int:
    """Ask Google whether this key can see the model. Generates nothing."""
    response = client.get(f"{API_BASE}/models/{model}", headers={KEY_HEADER: key})
    if response.status_code != 200:
        print(f"{model}: Gemini answered {response.status_code}: {_error_text(response, key)}")
        return 1
    print(f"{model}: available to this key")
    return 0


def main(argv: list[str] | None = None, client: httpx.Client | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the Gemini held-out set, once")
    parser.add_argument("--check", action="store_true", help="only ask whether the model is available")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    settings = get_settings()
    if not settings.gemini_api_key:
        print("GEMINI_API_KEY is not set in .env")
        return 2
    if not args.check and args.out.exists():
        print(f"{args.out} exists. The held-out set is written once; delete it yourself to start over.")
        return 2
    with client or httpx.Client(timeout=TIMEOUT_S) as http:
        if args.check:
            return check(http, settings.gemini_model, settings.gemini_api_key)
        try:
            rows, meta = generate(http, settings.gemini_model, settings.gemini_api_key)
        except (GeminiError, httpx.HTTPError) as exc:
            print(f"stopped, nothing written: {type(exc).__name__}: {str(exc).replace(settings.gemini_api_key, '[key]')}")
            return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    write_json(meta, args.out.with_suffix(".meta.json"))
    print(f"wrote {len(rows)} transcripts to {args.out} ({meta['requests']} requests, {meta['extra_rounds']} extra rounds)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
