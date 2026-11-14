"""The words on the screen: the client's dictionary against docs/design and the server.

The copy is the readable half of the safety feature, and the browser code has no test
runner, so these read `web/` as text. They check wording, never layout.
"""

from __future__ import annotations

import re

from server.config import WEB_DIR
from server.explainer import GENERIC_SAFE_EXIT

APP_JS = (WEB_DIR / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (WEB_DIR / "index.html").read_text(encoding="utf-8")

# Fixed in docs/design/ (screens.md and components/*.md). Changing one is a SPEC change.
FIXED_COPY = (
    "Put the call on speaker next to this phone.",
    "Start listening",
    "Demo mode",
    "The call will appear here.",
    "Listening.",
    "Calm",
    "Watch",
    "Scam",
    "Real call",
    "Marked as a real call. Alerts are off for this call.",
    "Be careful",
    "This sounds like a scam",
    "SAY THIS",
    "CALL BACK",
    "Use the number on your card or your last statement.",
    "This is a real call",
    "Do not read that number out",
    "Hang up, then call back on a number you know.",
    "{count} digits heard.",
    "Recorded call, replayed through the same pipeline.",
    "Nothing here is live. The mic is off in demo mode.",
)


def test_every_fixed_string_is_in_the_dictionary_word_for_word():
    missing = [text for text in FIXED_COPY if f'"{text}"' not in APP_JS]
    assert missing == []


def test_the_default_line_to_say_is_the_servers_generic_line():
    assert f'safe_exit_default: "{GENERIC_SAFE_EXIT}"' in APP_JS


def test_every_copy_key_the_page_asks_for_exists():
    asked = set(re.findall(r'data-copy(?:-label)?="([a-z_]+)"', INDEX_HTML))
    defined = set(re.findall(r"^\s{4}([a-z_]+):", APP_JS, flags=re.MULTILINE))
    assert asked, "the page should take its words from the dictionary"
    assert asked - defined == set()


def test_the_page_holds_no_words_of_its_own():
    # Text between tags would be copy that Spanish could never reach.
    body = INDEX_HTML.split("<body>", 1)[1]
    without_comments = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    loose_text = [text.strip() for text in re.findall(r">([^<]+)<", without_comments)]
    assert [text for text in loose_text if text and not text.startswith("&#")] == []


def test_the_client_never_logs_to_the_console():
    for path in sorted(WEB_DIR.glob("*.js")):
        assert "console." not in path.read_text(encoding="utf-8"), path.name
