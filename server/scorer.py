"""Turns a running transcript into one risk number.

In: everything said so far, as plain text with no speaker labels.
Out: a risk from 0.0 to 1.0 from the fine-tuned DistilBERT, over the last 256 tokens.
It does not decide alerts, call the LLM, or look at audio.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from server.config import get_settings

# Frozen by docs/SPEC.md §2 and by how the model was trained (ml/README.md).
MAX_TOKENS = 256
TRUNCATION_SIDE = "left"


class RiskScorer(Protocol):
    """Anything that maps a transcript to 0..1. Tests inject their own."""

    name: str

    def score(self, transcript: str) -> float: ...


class StubScorer:
    """Stand-in until ml/ produces the model. Always 0.0, never an alert.

    The pipeline runs end to end with this so the app can be built against the
    real wire protocol while training happens in Colab.
    """

    name = "stub"

    def score(self, transcript: str) -> float:
        return 0.0


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
        self._model = None
        self._tokenizer = None

    @classmethod
    def load(cls, model_dir: Path | None = None, device: str = "cpu") -> "DistilBertRiskScorer":
        """Point at a folder and return a scorer that will load on first use."""
        return cls(model_dir or get_settings().risk_model_dir, device=device)

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def ensure_loaded(self) -> None:
        """Load tokenizer and weights from `model_dir`. Idempotent."""
        raise NotImplementedError("scorer lands in phase 3 — docs/SPEC.md §4")

    def score(self, transcript: str) -> float:
        """Risk for the transcript tail.

        Empty or whitespace-only input scores 0.0. The text is truncated from the
        left to `MAX_TOKENS`, matching how training saw prefixes; no speaker tags,
        because live transcripts have none.
        """
        raise NotImplementedError("scorer lands in phase 3 — docs/SPEC.md §4")


def load_scorer(model_dir: Path | None = None) -> RiskScorer:
    """Use the trained model when its folder exists, the stub otherwise.

    A missing folder is the normal state until phase 2 lands; it is not an error.
    """
    target = Path(model_dir or get_settings().risk_model_dir)
    if (target / "config.json").is_file():
        return DistilBertRiskScorer.load(target)
    return StubScorer()
