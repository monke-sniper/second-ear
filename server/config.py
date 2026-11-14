"""Settings read once from the environment, plus repo paths.

Every module asks `get_settings()` instead of reading os.environ, so the model id,
the ntfy topic and the model folder have exactly one home. This file holds no
behaviour and never writes anything.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "models"
CALLS_DIR = ROOT / "eval" / "calls"

# The one place the Haiku id is written. Overridable from .env for the weekend.
DEFAULT_HAIKU_MODEL = "claude-haiku-5-5"

load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None
    haiku_model: str
    ntfy_topic: str | None
    ntfy_base_url: str
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    risk_model_dir: Path
    orgs_path: Path

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_ntfy(self) -> bool:
        return bool(self.ntfy_topic and not self.ntfy_topic.startswith("second-ear-replace"))


def _path(value: str | None, default: Path) -> Path:
    if not value:
        return default
    candidate = Path(value)
    return candidate if candidate.is_absolute() else ROOT / candidate


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Read the environment once. Call this, never `os.environ` directly."""
    env = os.environ.get
    return Settings(
        anthropic_api_key=env("ANTHROPIC_API_KEY") or None,
        haiku_model=env("ANTHROPIC_MODEL", DEFAULT_HAIKU_MODEL),
        ntfy_topic=env("NTFY_TOPIC") or None,
        ntfy_base_url=env("NTFY_BASE_URL", "https://ntfy.sh"),
        whisper_model=env("WHISPER_MODEL", "base.en"),
        whisper_device=env("WHISPER_DEVICE", "cuda"),
        whisper_compute_type=env("WHISPER_COMPUTE_TYPE", "float16"),
        risk_model_dir=_path(env("RISK_MODEL_DIR"), DATA_DIR / "risk-scorer"),
        orgs_path=Path(__file__).resolve().parent / "orgs.json",
    )
