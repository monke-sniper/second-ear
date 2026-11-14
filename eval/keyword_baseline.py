"""The keyword baseline: a fixed list of phrases, any hit means scam.

In: a transcript. Out: the listed phrases found in it, and 1 or 0.
It is not the app's stand-in scorer and it is never tuned. The list and the matching rule
are copied from ml/baselines.ipynb (and ml/README.md); a test pins them to baselines.json.
"""

from __future__ import annotations

import re

# The fixed list from ml/README.md. It was set before any test split was scored.
KEYWORDS = (
    "gift card",
    "wire transfer",
    "bitcoin",
    "don't tell anyone",
    "remote access",
    "warrant",
    "medicare number",
)
RULE = "any listed phrase present; case-insensitive, whole phrase, plural allowed"


def keyword_pattern(phrase: str) -> re.Pattern:
    """A whole-phrase matcher that tolerates extra spaces and a plural s."""
    words = [re.escape(word) for word in phrase.split()]
    return re.compile(r"\b" + r"\s+".join(words) + r"s?\b")


KEYWORD_PATTERNS = {phrase: keyword_pattern(phrase) for phrase in KEYWORDS}


def keyword_hits(text: str) -> list[str]:
    """Every listed phrase found in the text."""
    lowered = text.lower().replace("’", "'")
    return [phrase for phrase, pattern in KEYWORD_PATTERNS.items() if pattern.search(lowered)]


def predict(text: str) -> int:
    """1 (scam) when any phrase is present, else 0."""
    return int(bool(keyword_hits(text)))
