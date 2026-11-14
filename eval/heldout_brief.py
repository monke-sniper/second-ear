"""The brief Gemini is given for the held-out set, and the 100 slots it fills.

In: nothing. Out: the brief text, one line per kind of call, and the plan of 100 slots
(50 scam, 50 legitimate) with the opening of each call decided here, not by the model.
It does not call Gemini and does not know any scorer's phrase list. It was written before
the first request and must not change after the set exists.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

OPENINGS = ("hello", "hi", "none", "this is")

BRIEF = """\
You are writing test data for a research project that studies phone scams aimed at older adults.
Each item you write is the transcript of one short phone call received by an older person at
home in the United States. Some calls are scams and some are honest. Each request names one kind
of call and lists the items to write.

Rules for every transcript:

1. Length: 90 to 170 words, as one paragraph.
2. Write it the way a speech-to-text program would hear the call on speakerphone: the words of
   both people, in the order they were spoken, run together as plain text. No speaker names, no
   labels such as "Caller:", no line breaks, no quotation marks, no stage directions, no notes
   in brackets.
3. Everyday spoken American English. People may hesitate, interrupt or repeat themselves a
   little.
4. The first words follow the item's "opening":
   - "hello": the first word is Hello.
   - "hi": the first word is Hi.
   - "this is": the first words are This is.
   - "none": there is no greeting. The first words go straight to the matter. They are not
     Hello, Hi, Hey, Good morning, Good afternoon, Good evening or This is.
5. Never write a phone number, a street or web address, or the digits of any account, card,
   government ID or code. People may talk about these things without saying the digits.
   Amounts of money are fine.
6. Use invented names for people.

When the request says the calls are scams: the caller is running that scam on the person. Make
it realistic, not a cartoon. Some callers are smooth and patient, some are pushy. The caller
never says that it is a scam. The person who answers may be trusting, confused or suspicious,
and the call may end before any money or information changes hands.

When the request says the calls are legitimate: each is an honest call of that kind and nothing
dishonest happens in it. Make several of them tricky: an honest call can still involve money,
account security, a deadline, an identity check, or a relative asking for help.

Within one request, make the calls differ from each other: who is calling, the reason given,
the tone, and how the call ends.

Return JSON only, in the shape the request asks for.
"""


@dataclass(frozen=True)
class Scenario:
    """One kind of call. `line` names the situation and nothing more."""

    label: int  # 1 scam, 0 legitimate
    type: str
    line: str
    count: int


@dataclass(frozen=True)
class Slot:
    """One transcript to be written."""

    id: str
    label: int
    type: str
    opening: str


SCENARIOS = (
    Scenario(1, "grandparent", "The caller pretends to be the person's grandchild, or to be speaking for the grandchild.", 6),
    Scenario(1, "medicare", "The caller pretends to be from Medicare.", 6),
    Scenario(1, "ssn", "The caller pretends to be from the Social Security Administration, and the call is about the person's Social Security number.", 6),
    Scenario(1, "irs", "The caller pretends to be from the IRS.", 6),
    Scenario(1, "tech_support", "The caller pretends to be technical support for the person's computer or phone.", 6),
    Scenario(1, "gift_card", "The caller, whoever they claim to be, wants to be paid with gift cards.", 5),
    Scenario(1, "bank_fraud", "The caller pretends to be the fraud department of the person's bank.", 5),
    Scenario(1, "prize", "The caller says the person has won a prize.", 5),
    Scenario(1, "romance", "The caller is someone the person met online and has never met in person, and the relationship is romantic.", 5),
    Scenario(0, "pharmacy", "The person's pharmacy calls.", 9),
    Scenario(0, "doctor", "The person's doctor's office calls.", 9),
    Scenario(0, "bank_fraud_real", "The real fraud department of the person's bank calls about a charge on the account.", 8),
    Scenario(0, "grandchild_40", "The person's real grandchild calls and asks to borrow forty dollars.", 8),
    Scenario(0, "delivery", "A delivery driver or a delivery company calls about a package.", 8),
    Scenario(0, "utility", "The person's electric, gas, water or phone company calls.", 8),
)


def build_plan() -> list[Slot]:
    """The 100 slots, scam first. Openings are dealt by position within each label, by
    one rule for both, so each label gets the same number of every opening."""
    plan: list[Slot] = []
    for label, prefix in ((1, "scam"), (0, "legit")):
        position = 0
        for scenario in SCENARIOS:
            if scenario.label != label:
                continue
            for number in range(1, scenario.count + 1):
                opening = OPENINGS[position % len(OPENINGS)]
                plan.append(Slot(f"{prefix}-{scenario.type}-{number:02d}", label, scenario.type, opening))
                position += 1
    return plan


def batch_request(scenario: Scenario, slots: list[Slot]) -> str:
    """The user message for one kind of call: what it is and which items to write."""
    kind = "scams" if scenario.label == 1 else "legitimate"
    lines = [
        f"Kind of call: {scenario.line}",
        f"These calls are {kind}.",
        f"Write {len(slots)} transcripts, one for each item:",
    ]
    lines.extend(f'- id "{slot.id}", opening "{slot.opening}"' for slot in slots)
    lines.append('Return {"transcripts": [{"id": "...", "text": "..."}]} with exactly these ids.')
    return "\n".join(lines)


def spec_sha256() -> str:
    """A fingerprint of everything the generator was told: brief, scenarios, openings."""
    spec = {
        "brief": BRIEF,
        "openings": list(OPENINGS),
        "scenarios": [[s.label, s.type, s.line, s.count] for s in SCENARIOS],
    }
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode("utf-8")).hexdigest()
