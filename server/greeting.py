"""The training greeting rule, so the live scorer reads what the model was trained on.

In: a transcript from the start of the call. Out: the same text without one leading greeting.
It does not score, tokenize or truncate, and it never touches a greeting later in the call.

The pattern and the function are copied verbatim from ml/README.md (the notebooks' shared
helpers cell). Do not edit them here: change training first, then copy again, and update the
test that pins the pattern.
"""

from __future__ import annotations

import re

GREETING_PATTERN = re.compile(
    r"^\s*(?:hello|hi|hey|good\s+(?:morning|afternoon|evening))\b[\s,.!?;:\-\u2013\u2014]*", re.IGNORECASE
)


def strip_greeting(text: str) -> str:
    """Remove one leading greeting (hello, hi, hey, good morning / afternoon / evening) and the
    punctuation after it. The same rule for every row and both labels: in this dataset the
    greeting alone nearly gives the label away."""
    return GREETING_PATTERN.sub("", text, count=1)
