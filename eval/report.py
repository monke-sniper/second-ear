"""Turns replays of recorded calls into rows, totals and the list of wrong calls.

In: each call's label and its replay. Out: one row per call, the totals as results rows
(each with its n), and the text of failures.md with every number in a snippet replaced.
It does not run audio, load a model or write a file; run_eval.py does that.
"""

from __future__ import annotations

import re
import statistics
from typing import Any, Sequence

from eval.labels import CallLabel
from eval.metrics import rounded
from eval.replay import Replay
from server.contracts import AlertLevel, TranscriptChunk
from server.numbers import replace_number_runs

TEST = "recorded_calls"
SNIPPET_WORDS = 60
SNIPPET_AROUND_S = 10.0
REDACTED = "[number]"
_DIGITS = re.compile(r"\d+")
# Fixed before any recorded call was scored (docs/SPEC.md §8).
CAUGHT_RULE = "caught = any alert, caution or scam"
TIME_NOTE = "audio time at the end of the chunk that raised the alert; a live call adds the decode time"


def call_row(label: CallLabel, replay: Replay) -> dict[str, Any]:
    """The facts about one call. No transcript text."""
    alerts = [step.alert for step in replay.steps if step.alert is not None]
    risks = [step.risk for step in replay.steps if step.risk is not None]
    first = alerts[0] if alerts else None
    scam = next((alert for alert in alerts if alert.level is AlertLevel.scam), None)
    danger = next((step.danger for step in replay.steps if step.danger is not None), None)
    peak = max(risks, key=lambda risk: risk.score, default=None)
    asked = label.label == 1 and label.money_ask_s is not None
    return {
        "file": label.file,
        "label": label.label,
        "scam_type": label.scam_type,
        "duration_s": round(replay.duration_s, 2),
        "money_ask_s": label.money_ask_s,
        "first_alert_level": first.level.value if first else None,
        "first_alert_t_s": round(first.t_s, 2) if first else None,
        "first_alert_trigger": first.trigger if first else None,
        "first_alert_score": rounded(first.score) if first else None,
        "scam_alert_t_s": round(scam.t_s, 2) if scam else None,
        "alerted_before_ask": (first is not None and first.t_s < label.money_ask_s) if asked else None,
        "danger_fired": danger is not None,
        "danger_t_s": round(danger.t_s, 2) if danger else None,
        "peak_score": rounded(peak.score) if peak else None,
        "peak_t_s": round(peak.t_s, 2) if peak else None,
        "chunks": len(risks),
        "tail_s": round(replay.tail_s, 2),
        "timeline": [{"t_s": round(r.t_s, 2), "score": rounded(r.score), "level": r.level.value} for r in risks],
    }


def verdict(row: dict[str, Any]) -> str:
    """`missed`, `false_alarm`, `late` (caught, but after the ask) or `ok`."""
    alerted = row["first_alert_level"] is not None
    if row["label"] == 1:
        if not alerted:
            return "missed"
        return "late" if row["alerted_before_ask"] is False else "ok"
    return "false_alarm" if alerted else "ok"


def _rate(hits: int, n: int) -> float | None:
    return rounded(hits / n) if n else None


def summarize(rows: Sequence[dict[str, Any]], scorer_name: str) -> list[dict[str, Any]]:
    """The totals, one results row per number, each with its own denominator."""
    scam = [row for row in rows if row["label"] == 1]
    legit = [row for row in rows if row["label"] == 0]
    caught = [row for row in scam if row["first_alert_level"] is not None]
    asked = [row for row in scam if row["money_ask_s"] is not None]
    times = [row["first_alert_t_s"] for row in caught]
    tail = f"{len(rows)} calls in all; scorer {scorer_name}"

    def count(group: Sequence[dict], key: str) -> int:
        return sum(1 for row in group if row[key] not in (None, False))

    def row(metric: str, value: float | None, n: int, notes: str) -> dict[str, Any]:
        return {"test": TEST, "metric": metric, "value": value, "n": n, "notes": f"{notes}; {tail}"}

    return [
        row("catch_rate", _rate(len(caught), len(scam)), len(scam), f"n = scam calls; {CAUGHT_RULE}; {len(caught)} caught, {len(scam) - len(caught)} missed"),
        row("catch_rate_scam_level", _rate(count(scam, "scam_alert_t_s"), len(scam)), len(scam), "n = scam calls; only a scam-level alert counts"),
        row("false_alarm_rate", _rate(count(legit, "first_alert_level"), len(legit)), len(legit), f"n = legitimate calls; any alert, caution or scam; {count(legit, 'first_alert_level')} alerted"),
        row("false_alarm_rate_scam_level", _rate(count(legit, "scam_alert_t_s"), len(legit)), len(legit), "n = legitimate calls; only a scam-level alert counts"),
        row("median_seconds_to_first_alert", round(statistics.median(times), 2) if times else None, len(times), f"n = scam calls that raised an alert; {TIME_NOTE}"),
        row("alerted_before_money_ask", _rate(count(asked, "alerted_before_ask"), len(asked)), len(asked), "n = scam calls with a money_ask_s in labels.csv; first alert strictly before it"),
        row("danger_fired_rate", _rate(count(scam, "danger_fired"), len(scam)), len(scam), "n = scam calls; the digit warning fired"),
        row("danger_fired_rate_legitimate", _rate(count(legit, "danger_fired"), len(legit)), len(legit), "n = legitimate calls; the digit warning fired"),
    ]


def redact(text: str) -> str:
    """No written digit and no spoken number of two digits or more, as on the wire."""
    return _DIGITS.sub(REDACTED, replace_number_runs(text, 2, REDACTED))


def snippet(row: dict[str, Any], chunks: Sequence[TranscriptChunk]) -> str:
    """Up to `SNIPPET_WORDS` words from where the call went wrong, numbers replaced.

    A false alarm: what was said up to the alert. A miss: what was said around the
    money ask when it is labelled, else the end of the call.
    """
    centre = row["first_alert_t_s"] if row["label"] == 0 else row["money_ask_s"]
    if centre is None:
        picked = list(chunks)
    else:
        picked = [c for c in chunks if c.end_s <= centre + SNIPPET_AROUND_S and c.end_s >= centre - 2 * SNIPPET_AROUND_S]
    words = " ".join(chunk.text for chunk in picked or chunks).split()
    return redact(" ".join(words[-SNIPPET_WORDS:]))


def failures_markdown(rows: Sequence[dict[str, Any]], snippets: dict[str, str], scorer_name: str, caveats: Sequence[str]) -> str:
    """failures.md: every missed scam and every false alarm, then the late alerts."""
    by_verdict = {name: [row for row in rows if verdict(row) == name] for name in ("missed", "false_alarm", "late")}
    scam_n = sum(1 for row in rows if row["label"] == 1)
    legit_n = len(rows) - scam_n
    lines = [
        "# Wrong calls",
        "",
        f"From `eval/run_eval.py`, scorer `{scorer_name}`. A scam call with no alert is a miss; a",
        "legitimate call with any alert is a false alarm. The lines below are facts from the run,",
        "and numbers in the snippets are replaced. The reason in words is for a person to add",
        "after listening.",
        "",
        *[f"- {note}" for note in caveats],
        "",
        f"## Missed scams ({len(by_verdict['missed'])} of {scam_n} scam calls)",
        "",
    ]
    for row in by_verdict["missed"]:
        ask = "not labelled" if row["money_ask_s"] is None else f"at {row['money_ask_s']} s"
        lines += [
            f"### {row['file']} ({row['scam_type'] or 'type not labelled'})",
            f"- No alert. Peak score {row['peak_score']} at {row['peak_t_s']} s; a caution needs a smoothed score of 0.50.",
            f"- Money ask {ask}. Call length {row['duration_s']} s.",
            f"- Heard: \"{snippets.get(row['file'], '')}\"",
            "",
        ]
    lines += [f"## False alarms ({len(by_verdict['false_alarm'])} of {legit_n} legitimate calls)", ""]
    for row in by_verdict["false_alarm"]:
        lines += [
            f"### {row['file']}",
            f"- {row['first_alert_level']} alert at {row['first_alert_t_s']} s (trigger `{row['first_alert_trigger']}`, score {row['first_alert_score']}). Peak score {row['peak_score']}.",
            f"- Heard: \"{snippets.get(row['file'], '')}\"",
            "",
        ]
    lines += ["## Late alerts (after the money ask; counted as caught)", ""]
    lines += [f"- {row['file']}: first alert at {row['first_alert_t_s']} s, money ask at {row['money_ask_s']} s." for row in by_verdict["late"]]
    return "\n".join(lines).rstrip() + "\n"
