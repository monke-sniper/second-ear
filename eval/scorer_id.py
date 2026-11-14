"""Says which scorer produced a results file.

In: the scorer the app loaded. Out: a small dict for the results file, and the note to
write when that scorer is the keyword stand-in and not a trained model.
It does not score anything and never loads model weights; it only hashes files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from eval.metrics import file_sha256
from server.config import ROOT, get_settings
from server.scorer import STAND_IN_WINDOW_WORDS, KeywordStandInScorer, RedFlag

MODEL_JSON = ROOT / "eval" / "results" / "model.json"
WEIGHTS_FILE = "model.safetensors"
STAND_IN_NOTE = (
    "The system scored here is the keyword stand-in (RED_FLAGS in server/scorer.py), not a "
    "trained model: models/risk-scorer/ did not exist when this ran."
)


def flags_sha256(flags: tuple[RedFlag, ...]) -> str:
    """A fingerprint of the stand-in's phrase list, so a later edit to it shows."""
    listed = [[flag.weight, list(flag.phrases)] for flag in flags]
    return hashlib.sha256(json.dumps(listed).encode("utf-8")).hexdigest()


def _exported_sha(model_json: Path) -> str | None:
    """The weights hash model.json says it was made from, if it can be read."""
    try:
        payload = json.loads(model_json.read_text(encoding="utf-8"))
        return payload["export"]["model_safetensors_sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def describe_scorer(scorer: Any, model_json: Path = MODEL_JSON) -> dict[str, Any]:
    """Name the scorer and tie it to its files.

    `model_json_sha256` is the hash of eval/results/model.json when that file exists.
    For the trained model, `weights_sha256` is the hash of the loaded weights and
    `weights_match_model_json` says whether model.json describes those same weights.
    """
    is_stand_in = isinstance(scorer, KeywordStandInScorer)
    folder = Path(getattr(scorer, "model_dir", None) or get_settings().risk_model_dir)
    weights = folder / WEIGHTS_FILE
    weights_sha = file_sha256(weights) if not is_stand_in and weights.is_file() else None
    exported = _exported_sha(model_json)
    info: dict[str, Any] = {
        "name": getattr(scorer, "name", type(scorer).__name__),
        "is_stand_in": is_stand_in,
        "model_folder_found": (folder / "config.json").is_file(),
        "model_json_sha256": file_sha256(model_json) if model_json.is_file() else None,
        "weights_sha256": weights_sha,
        "weights_match_model_json": (
            None if weights_sha is None or exported is None else weights_sha == exported
        ),
    }
    if is_stand_in:
        info["stand_in"] = {
            "flags": len(scorer.flags),
            "window_words": STAND_IN_WINDOW_WORDS,
            "flags_sha256": flags_sha256(scorer.flags),
        }
    return info


def scorer_caveats(info: dict[str, Any]) -> list[str]:
    """What a results file must say about its scorer, in words."""
    return [STAND_IN_NOTE] if info.get("is_stand_in") else []
