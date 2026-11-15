"""Finds numbers in transcript text, whether they were spoken or written.

In: a piece of text. Out: where each number sits and how many digits it holds.
It knows nothing about risk, time windows, prompts or pushes, and it never logs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# What docs/SPEC.md calls "a digit run": six or more digits.
DIGIT_RUN = 6

_UNITS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}  # fmt: skip
_TEENS = {
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19",
}  # fmt: skip
_TENS = {
    "twenty": "2", "thirty": "3", "forty": "4", "fifty": "5",
    "sixty": "6", "seventy": "7", "eighty": "8", "ninety": "9",
}  # fmt: skip
_MULTIPLIERS = {"double": 2, "triple": 3}
_OH = "oh"

_WORD = re.compile(r"\d+|[A-Za-z]+")
# What may sit between two numbers without ending the run: "four, five", "4-1-1",
# "four, uh, five". Punctuation, dashes and filler sounds; any real word ends it.
_RUN_GAP = re.compile(
    r"(?:[\s,.\-–—…]|\b(?:uh|um|er|erm|ah|hmm)\b)*", re.IGNORECASE
)
# What may sit inside one spoken number: "double seven", "forty-one".
_WORD_GAP = re.compile(r"[\s\-]*")


@dataclass(frozen=True)
class NumberRun:
    """Where one spoken or written number sits in a text.

    `digits` is transient and hidden from repr, so a log line or a failed assert
    that prints a run shows its position and nothing else.
    """

    start: int
    end: int
    digits: str = field(repr=False)

    @property
    def digit_count(self) -> int:
        return len(self.digits)


@dataclass(frozen=True)
class _Word:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class _Atom:
    """One number word, or a pair that reads as one ("double seven", "forty one")."""

    start: int
    end: int
    digits: str = field(repr=False)
    is_oh: bool = False


def _single_digit(text: str) -> str | None:
    """The one digit a word stands for, if it stands for exactly one."""
    if text in _UNITS:
        return _UNITS[text]
    if text == _OH:
        return "0"
    if text.isdigit() and len(text) == 1:
        return text
    return None


def _pair_atom(word: _Word, follower: _Word | None) -> _Atom | None:
    """ "double seven" → 77, "triple oh" → 000, "forty one" → 41. Otherwise None."""
    if follower is None:
        return None
    digit = _single_digit(follower.text)
    if digit is None:
        return None
    if word.text in _MULTIPLIERS:
        repeated = digit * _MULTIPLIERS[word.text]
        return _Atom(word.start, follower.end, repeated, is_oh=follower.text == _OH)
    if word.text in _TENS and follower.text in _UNITS and digit != "0":
        return _Atom(word.start, follower.end, _TENS[word.text] + digit)
    return None


def _single_atom(word: _Word) -> _Atom | None:
    """One word read on its own: a numeral, a unit, a teen, a bare ten, or "oh"."""
    text = word.text
    if text == _OH:
        return _Atom(word.start, word.end, "0", is_oh=True)
    if text.isdigit():
        digits = text
    elif text in _UNITS:
        digits = _UNITS[text]
    elif text in _TEENS:
        digits = _TEENS[text]
    elif text in _TENS:
        digits = _TENS[text] + "0"
    else:
        return None
    return _Atom(word.start, word.end, digits)


def _atoms(text: str) -> list[_Atom]:
    words = [_Word(m.start(), m.end(), m.group().lower()) for m in _WORD.finditer(text)]
    atoms: list[_Atom] = []
    index = 0
    while index < len(words):
        word = words[index]
        follower = words[index + 1] if index + 1 < len(words) else None
        if follower is not None and not _WORD_GAP.fullmatch(text, word.end, follower.start):
            follower = None
        pair = _pair_atom(word, follower)
        if pair is not None:
            atoms.append(pair)
            index += 2
            continue
        single = _single_atom(word)
        if single is not None:
            atoms.append(single)
        index += 1
    return atoms


def _trim_loose_oh(text: str, group: list[_Atom]) -> list[_Atom]:
    """Drop an "oh" at either end of a run unless it touches its neighbour.

    "oh four" and "four oh" keep their zero. "Oh, four of them" and "four. Oh, I
    forgot" do not: there the "oh" is a sigh. An "oh" between two numbers counts.
    """
    start, end = 0, len(group)
    while end - start > 1 and group[start].is_oh:
        if _WORD_GAP.fullmatch(text, group[start].end, group[start + 1].start):
            break
        start += 1
    while end - start > 1 and group[end - 1].is_oh:
        if _WORD_GAP.fullmatch(text, group[end - 2].end, group[end - 1].start):
            break
        end -= 1
    return group[start:end]


def find_number_runs(text: str, *, trim_loose_oh: bool = True) -> list[NumberRun]:
    """Every number in `text`, spoken or written, as one run per number.

    Number words and numerals separated only by spaces, commas, dots, dashes or
    filler sounds belong to the same run, so "4111 1111", "four, uh, five" and
    "Four. Five." are each one run. "oh" is a zero only next to another number
    word: "oh four" is 04, "oh, really" is not a number.

    `trim_loose_oh=False` is the cautious reading, for redaction only: an "oh" at the
    edge of a run stays in it even across a comma or a full stop ("One. Oh."). An "oh"
    with no number in its run is still not a number.
    """
    groups: list[list[_Atom]] = []
    for atom in _atoms(text):
        if groups and _RUN_GAP.fullmatch(text, groups[-1][-1].end, atom.start):
            groups[-1].append(atom)
        else:
            groups.append([atom])
    trimmed = [_trim_loose_oh(text, group) for group in groups] if trim_loose_oh else groups
    return [
        NumberRun(group[0].start, group[-1].end, "".join(atom.digits for atom in group))
        for group in trimmed
        if not all(atom.is_oh for atom in group)
    ]


def has_number_run(text: str, min_digits: int) -> bool:
    """True when `text` holds a number of at least `min_digits` digits."""
    return any(run.digit_count >= min_digits for run in find_number_runs(text))


def replace_number_runs(
    text: str,
    min_digits: int,
    replacement: str | None = None,
    *,
    trim_loose_oh: bool = True,
) -> str:
    """Rewrite every number holding at least `min_digits` digits.

    With `replacement` the number becomes that text (redaction). Without it the
    number becomes its digits (normalisation, for counting only). `trim_loose_oh` is
    passed to `find_number_runs`.
    """
    pieces: list[str] = []
    cursor = 0
    for run in find_number_runs(text, trim_loose_oh=trim_loose_oh):
        if run.digit_count < min_digits:
            continue
        pieces.append(text[cursor : run.start])
        pieces.append(run.digits if replacement is None else replacement)
        cursor = run.end
    pieces.append(text[cursor:])
    return "".join(pieces)
