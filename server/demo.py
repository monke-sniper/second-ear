"""Picks the recording the demo console replays.

In: the folder that holds the eval recordings. Out: the consented demo call if it is
there, the synthetic-voice call if not, or None.
It does not read, decode or change any audio, and it takes nothing from a request.
"""

from __future__ import annotations

from pathlib import Path

# In order of preference: a real recorded call, then the text-to-speech one.
DEMO_FILES = ("demo_scam.wav", "tts_scam.wav")


def find_demo_audio(calls_dir: Path) -> Path | None:
    """The first demo file that exists in `calls_dir`, or None.

    Only the two fixed names are ever looked for, so no other recording in the
    folder can be served by mistake.
    """
    for name in DEMO_FILES:
        candidate = calls_dir / name
        if candidate.is_file():
            return candidate
    return None
