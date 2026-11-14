"""Turns a running transcript into one risk number.

In: everything said so far, as plain text with no speaker labels.
Out: a risk from 0.0 to 1.0 from the fine-tuned DistilBERT, over the last 256 tokens.
It does not decide alerts, call the LLM, or look at audio.
"""

from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from server.config import get_settings

# Frozen by docs/SPEC.md §2 and by how the model was trained (ml/README.md).
MAX_TOKENS = 256
TRUNCATION_SIDE = "left"
# Label 1 is "scam" in the training data (docs/SPEC.md §6).
SCAM_LABEL = 1

# How far back the stand-in looks. Not in SPEC: about a minute and a half of speech.
STAND_IN_WINDOW_WORDS = 200

_WORD = re.compile(r"[a-z0-9']+")


class RiskScorer(Protocol):
    """Anything that maps a transcript to 0..1. Tests inject their own."""

    name: str

    def score(self, transcript: str) -> float: ...


class StubScorer:
    """Always 0.0, never an alert. For code that needs a scorer and no behaviour."""

    name = "stub"

    def score(self, transcript: str) -> float:
        return 0.0


@dataclass(frozen=True)
class RedFlag:
    """One thing scam callers say, in the ways they say it. Counted once per call."""

    weight: float
    phrases: tuple[str, ...]


# Hand-set, not trained and not measured. They exist so the alerts can be seen working
# while the real model trains. Never quote a metric from this list.
RED_FLAGS: tuple[RedFlag, ...] = (
    RedFlag(0.45, ("gift card", "gift cards")),
    RedFlag(0.45, ("wire transfer", "wire the money", "western union", "moneygram")),
    RedFlag(0.45, ("arrest warrant", "warrant for your arrest", "warrant out for")),
    RedFlag(0.40, ("bitcoin", "crypto", "cryptocurrency")),
    RedFlag(0.40, ("don't tell", "dont tell", "do not tell", "keep it a secret", "our secret")),
    RedFlag(0.40, ("remote access", "anydesk", "teamviewer", "team viewer")),
    RedFlag(0.35, ("bail",)),
    RedFlag(0.35, ("in jail", "arrested", "under arrest")),
    RedFlag(0.35, ("social security number", "your social security")),
    RedFlag(0.35, ("verification code", "security code", "read me the code", "the code on the")),
    RedFlag(0.30, ("stay on the line", "don't hang up", "dont hang up", "do not hang up")),
    RedFlag(0.30, ("lottery", "you have won", "you've won", "prize")),
    RedFlag(0.30, ("irs", "federal agent", "social security administration")),
    RedFlag(0.25, ("suspended", "suspicious activity", "compromised")),
    RedFlag(0.25, ("processing fee", "pay a fee", "taxes up front")),
    RedFlag(0.20, ("in trouble",)),
    RedFlag(0.20, ("refund",)),
    RedFlag(0.20, ("bank account", "routing number", "account number")),
    RedFlag(0.15, ("accident",)),
    RedFlag(0.15, ("lawyer", "attorney")),
    RedFlag(0.15, ("right away", "right now", "immediately", "act now", "urgent")),
    RedFlag(0.10, ("grandma", "grandpa", "grandmother", "grandfather")),
    RedFlag(0.10, ("grandson", "granddaughter")),
)


class KeywordStandInScorer:
    """Stand-in until `models/risk-scorer/` exists: weighted red-flag phrases.

    Looks at the last `STAND_IN_WINDOW_WORDS` words. Each flag heard adds its weight
    once, combined so the result climbs towards 1.0 and never passes it
    (`1 - product(1 - weight)`). It is a placeholder that makes the alert path
    visible, not a model: it has no accuracy claim and is not the keyword baseline
    in ml/.
    """

    name = "keyword-stand-in"

    def __init__(self, flags: tuple[RedFlag, ...] = RED_FLAGS) -> None:
        self.flags = flags

    def score(self, transcript: str) -> float:
        words = _WORD.findall(transcript.lower().replace("’", "'"))
        if not words:
            return 0.0
        # Padded with spaces so "bail" matches the word and not "bailey".
        tail = " " + " ".join(words[-STAND_IN_WINDOW_WORDS:]) + " "
        heard = [flag.weight for flag in self.flags if _mentions(tail, flag)]
        return 1.0 - math.prod(1.0 - weight for weight in heard)


def _mentions(padded_text: str, flag: RedFlag) -> bool:
    return any(f" {phrase} " in padded_text for phrase in flag.phrases)


class DistilBertRiskScorer:
    """The trained scorer. Loads once, scores one 256-token window per call chunk.

    CPU by default: the model is 66M params and a window scores in ~30 ms, which is
    well inside the 4 s chunk cadence. Moving it to CUDA is a config change, not a
    code change.
    """

    name = "distilbert"

    def __init__(self, model_dir: Path, device: str = "cpu") -> None:
        self.model_dir = Path(model_dir)
        self.device = device
        self._lock = threading.Lock()
        self._model: Any = None
        self._tokenizer: Any = None

    @classmethod
    def load(cls, model_dir: Path | None = None, device: str = "cpu") -> "DistilBertRiskScorer":
        """Point at a folder and return a scorer that will load on first use."""
        return cls(model_dir or get_settings().risk_model_dir, device=device)

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def ensure_loaded(self) -> None:
        """Load tokenizer and weights from `model_dir`. Idempotent."""
        with self._lock:
            if self._model is not None:
                return
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(
                self.model_dir, truncation_side=TRUNCATION_SIDE
            )
            model = AutoModelForSequenceClassification.from_pretrained(self.model_dir)
            model.to(self.device)
            model.eval()
            self._tokenizer = tokenizer
            self._model = model

    def score(self, transcript: str) -> float:
        """Risk for the transcript tail.

        Empty or whitespace-only input scores 0.0. The text is truncated from the
        left to `MAX_TOKENS`, matching how training saw prefixes; no speaker tags,
        because live transcripts have none.
        """
        text = transcript.strip()
        if not text:
            return 0.0
        self.ensure_loaded()
        import torch

        inputs = self._tokenizer(
            text, truncation=True, max_length=MAX_TOKENS, return_tensors="pt"
        ).to(self.device)
        with torch.no_grad():
            logits = self._model(**inputs).logits[0]
        if logits.numel() == 1:
            risk = torch.sigmoid(logits[0])
        else:
            risk = torch.softmax(logits, dim=-1)[SCAM_LABEL]
        return min(1.0, max(0.0, float(risk)))


def load_scorer(model_dir: Path | None = None) -> RiskScorer:
    """Use the trained model when its folder exists, the stub otherwise.

    A missing folder is the normal state until phase 2 lands; it is not an error.
    """
    target = Path(model_dir or get_settings().risk_model_dir)
    if (target / "config.json").is_file():
        return DistilBertRiskScorer.load(target)
    return StubScorer()


def load_app_scorer(model_dir: Path | None = None) -> RiskScorer:
    """What the running app scores with: the trained model, or the keyword stand-in.

    Unlike `load_scorer`, a missing model folder gives a scorer that can raise an
    alert, so the whole path can be shown before training finishes.
    """
    target = Path(model_dir or get_settings().risk_model_dir)
    if (target / "config.json").is_file():
        return DistilBertRiskScorer.load(target)
    return KeywordStandInScorer()
