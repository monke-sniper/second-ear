"""Format checks for one generated transcript.

In: the slot it was written for and its text. Out: None when the format is right, or a
one-word reason. The reason never quotes the transcript.
It judges format only: length, opening, labels, markup, number runs. It never looks at
what a scorer would say, so no transcript is kept or dropped for being easy or hard.
"""

from __future__ import annotations

import re

from eval.heldout_brief import Slot
from server.greeting import GREETING_PATTERN
from server.numbers import has_number_run

WORDS_MIN = 60
WORDS_MAX = 220
# A single number this long, spoken or written, reads as a code, card or phone number.
NUMBER_RUN_MAX = 6

_STARTS = {
    "hello": re.compile(r"hello\b", re.IGNORECASE),
    "hi": re.compile(r"hi\b", re.IGNORECASE),
    "this is": re.compile(r"this\s+is\b", re.IGNORECASE),
}
# "Caller: ..." at the start or after a sentence end. Two of them make a labelled dialogue.
_LABEL = re.compile(r"(?:^|(?<=[.!?]\s))[A-Z][\w'.]*(?:\s[\w'.]+)?:\s")
_MARKUP = re.compile(r"[\[\]()*]")
_WRITTEN_NUMBERS = (re.compile(r"\d{5,}"), re.compile(r"\b\d{3}[-.\s]\d{3,4}\b"))

CHECKS = (
    f"{WORDS_MIN} to {WORDS_MAX} words",
    "first words match the slot's opening; 'none' has no greeting and no 'This is'",
    "no speaker labels",
    "no brackets, parentheses or asterisks",
    f"no number of {NUMBER_RUN_MAX}+ digits, spoken or written, and nothing shaped like a phone number",
)


def clean(text: object) -> str:
    """Collapse whitespace. Anything that is not text becomes the empty string."""
    return " ".join(text.split()) if isinstance(text, str) else ""


def opening_matches(opening: str, text: str) -> bool:
    """True when the first words of `text` are what the slot asked for."""
    if opening == "none":
        return not GREETING_PATTERN.match(text) and not _STARTS["this is"].match(text)
    return bool(_STARTS[opening].match(text))


def format_problem(slot: Slot, text: str) -> str | None:
    """The first format rule `text` breaks, or None. `text` is already cleaned."""
    if not text:
        return "missing"
    if not WORDS_MIN <= len(text.split()) <= WORDS_MAX:
        return "length"
    if not opening_matches(slot.opening, text):
        return "opening"
    if len(_LABEL.findall(text)) >= 2:
        return "labels"
    if _MARKUP.search(text):
        return "markup"
    if has_number_run(text, NUMBER_RUN_MAX) or any(p.search(text) for p in _WRITTEN_NUMBERS):
        return "numbers"
    return None
