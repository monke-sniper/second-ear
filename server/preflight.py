"""One command that says whether this machine can run the demo.

Checks Python, torch, CTranslate2 (CUDA), a one-second Whisper transcription, the
scorer folder, and the env keys. Prints PASS/WARN/FAIL per line and exits 1 only
when the Whisper path — the one thing a live demo cannot lose — fails.
It downloads a Whisper model only when the configured one is not cached yet.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.config import Settings


def _pass(msg: str) -> None:
    print(f"PASS  {msg}")


def _warn(msg: str) -> None:
    print(f"WARN  {msg}")


def _fail(msg: str) -> None:
    print(f"FAIL  {msg}")


def check_python() -> bool:
    v = sys.version_info
    where = "venv" if sys.prefix != sys.base_prefix else "base python — activate .venv"
    if (v.major, v.minor) >= (3, 11):
        _pass(f"python {v.major}.{v.minor}.{v.micro} ({where})")
        return True
    _fail(f"python {v.major}.{v.minor}.{v.micro} ({where}); 3.11+ required")
    return False


def check_torch() -> bool:
    try:
        import torch
    except Exception as exc:  # noqa: BLE001 - any failure here is the answer
        _fail(f"torch import: {exc}")
        return False
    _pass(f"torch {torch.__version__} (cpu is expected; cuda available: {torch.cuda.is_available()})")
    return True


def check_ctranslate2() -> bool:
    try:
        import ctranslate2 as ct2
    except Exception as exc:  # noqa: BLE001
        _fail(f"ctranslate2 import: {exc}")
        return False
    try:
        devices = ct2.get_cuda_device_count()
    except Exception:
        devices = 0
    try:
        types = sorted(ct2.get_supported_compute_types("cuda"))
    except Exception:
        types = []
    if devices > 0:
        _pass(f"ctranslate2 {ct2.__version__}: {devices} CUDA device(s), cuda compute types {types}")
        return True
    _fail(
        f"ctranslate2 {ct2.__version__}: no CUDA device visible. "
        "Whisper will fall back to CPU; fix before the demo if it matters."
    )
    return False


def check_whisper(settings: "Settings") -> bool:
    import numpy as np
    from faster_whisper import WhisperModel

    def load(device: str, compute_type: str) -> "WhisperModel":
        return WhisperModel(settings.whisper_model, device=device, compute_type=compute_type)

    started = time.perf_counter()
    try:
        model = load(settings.whisper_device, settings.whisper_compute_type)
        used = f"{settings.whisper_device}/{settings.whisper_compute_type}"
    except Exception as exc:  # noqa: BLE001
        _fail(f"whisper load on {settings.whisper_device}: {exc}")
        if settings.whisper_device == "cpu":
            return False
        _warn("retrying on cpu/int8 — set WHISPER_DEVICE=cpu in .env if this is the only path")
        try:
            model = load("cpu", "int8")
            used = "cpu/int8 (fallback)"
        except Exception as exc2:  # noqa: BLE001
            _fail(f"whisper load on cpu: {exc2}")
            return False
    load_s = time.perf_counter() - started

    silence = np.zeros(16_000, dtype=np.float32)
    started = time.perf_counter()
    try:
        segments, info = model.transcribe(
            silence, task="translate", vad_filter=True, beam_size=1
        )
        text = "".join(segment.text for segment in segments).strip()
    except Exception as exc:  # noqa: BLE001
        _fail(f"whisper transcribe on {used}: {exc}")
        return False
    elapsed_ms = (time.perf_counter() - started) * 1000
    _pass(
        f"whisper {settings.whisper_model} on {used}: load {load_s:.1f}s, "
        f"1 s of silence in {elapsed_ms:.0f} ms, text={text!r}"
    )
    return True


def check_import_isolation() -> bool:
    """A venv is only as good as what it actually imports.

    A globally exported PYTHONPATH or an activated conda env can put a foreign
    site-packages on sys.path, and then the lock file describes packages that never
    load. This caught exactly that in a spawned shell during scaffolding.
    """
    sites = [p for p in sys.path if p.replace("\\", "/").endswith(("site-packages", "dist-packages"))]
    prefix = sys.prefix.replace("\\", "/").lower()
    foreign = [p for p in sites if not p.replace("\\", "/").lower().startswith(prefix)]
    if foreign:
        _warn(f"foreign site-packages on sys.path: {foreign} — unset PYTHONPATH / deactivate conda")
        return False
    _pass(f"imports resolve inside {sys.prefix} only")
    return True


def check_model_dir(settings: Settings) -> bool:
    target: Path = settings.risk_model_dir
    if (target / "config.json").is_file():
        _pass(f"scorer folder {target}")
    else:
        _warn(f"no scorer at {target} — StubScorer (always 0.0) will be used")
    return True


def check_env(settings: Settings) -> bool:
    if settings.has_anthropic:
        _pass(f"ANTHROPIC_API_KEY set (model {settings.haiku_model})")
    else:
        _warn("ANTHROPIC_API_KEY missing — explainer will always use the generic line")
    if settings.has_ntfy:
        _pass(f"NTFY_TOPIC set (base {settings.ntfy_base_url})")
    else:
        _warn("NTFY_TOPIC missing or placeholder — pushes are disabled")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Second Ear environment preflight")
    parser.add_argument("--skip-whisper", action="store_true", help="skip the model load and transcription")
    args = parser.parse_args(argv)

    # Runs before any third-party import: a foreign site-packages kills the process
    # at numpy/torch import with a traceback that says nothing about the real cause.
    if not check_import_isolation():
        print("\nBLOCKED — fix PYTHONPATH / conda activation, then run this again.")
        return 1

    from server.config import ROOT, get_settings

    settings = get_settings()
    print(f"Second Ear preflight — {ROOT}\n")

    hard = [check_python(), check_torch(), check_ctranslate2()]
    if args.skip_whisper:
        _warn("whisper check skipped")
    else:
        hard.append(check_whisper(settings))
    check_model_dir(settings)
    check_env(settings)

    ok = all(hard)
    print("\nOK — ready for phase 3." if ok else "\nBLOCKED — fix the FAIL lines above.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
