"""The words on the screen: the client's dictionary against docs/design and the server.

The copy is the readable half of the safety feature, and the browser code has no test
runner, so these read `web/` as text. They check wording, never layout.
"""

from __future__ import annotations

import re

from server.config import ROOT, WEB_DIR
from server.explainer import GENERIC_SAFE_EXIT

APP_JS = (WEB_DIR / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (WEB_DIR / "index.html").read_text(encoding="utf-8")
PROMISE = "Second Ear never saves your calls."
# Ways a Python module puts something on disk. None may appear in server/.
FILE_WRITES = re.compile(
    r"\bopen\(|\.write\(|write_text|write_bytes|tempfile|wave\.open|pickle|sqlite|shelve|json\.dump\("
)

# Fixed in docs/design/ (screens.md and components/*.md). Changing one is a SPEC change.
FIXED_COPY = (
    "Put the call on speaker next to this phone.",
    PROMISE,
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
    "Recorded call, replayed through the same pipeline.",
    "Nothing here is live. The mic is off in demo mode.",
)


def test_every_fixed_string_is_in_the_dictionary_word_for_word():
    missing = [text for text in FIXED_COPY if f'"{text}"' not in APP_JS]
    assert missing == []


def test_the_default_line_to_say_is_the_servers_generic_line():
    assert f'safe_exit_default: "{GENERIC_SAFE_EXIT}"' in APP_JS


def test_the_danger_banner_is_its_two_fixed_lines_and_shows_no_count():
    # danger.digit_count stays on the wire for eval; the screen never shows it.
    banner = INDEX_HTML.split('id="danger-banner"', 1)[1].split("<main", 1)[0]
    assert re.findall(r'data-copy="([a-z_]+)"', banner) == ["danger_title", "danger_body"]
    assert re.findall(r"<p\b", banner) == ["<p", "<p"]
    for path in sorted(WEB_DIR.glob("*.js")):
        source = path.read_text(encoding="utf-8")
        assert "digits heard" not in source, path.name
        assert "digit_count" not in source, path.name


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


def test_the_promise_sits_under_the_status_line_and_shows_on_the_ready_screen_only():
    header = INDEX_HTML.split('<header class="app__bar">', 1)[1].split("</header>", 1)[0]
    assert re.findall(r'id="([a-z-]+)"', header) == ["status", "privacy-note"]
    assert 'id="privacy-note" data-copy="privacy_note" hidden' in header
    assert f'privacy_note: "{PROMISE}"' in APP_JS
    assert 'el("privacy-note").hidden = name !== "ready";' in APP_JS


def test_the_promise_is_kept_no_server_module_writes_a_file():
    # The promise is on the screen, so it has to stay true: nothing in server/ may put
    # audio, a transcript or anything else on disk. A write added later fails here.
    writers = [
        f"{path.name}:{number}"
        for path in sorted((ROOT / "server").glob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if FILE_WRITES.search(line)
    ]
    assert writers == []


def test_the_browser_stores_nothing_from_a_call():
    # The one thing kept is a flag that the mic prompt was explained once.
    stored = [
        (path.name, key)
        for path in sorted(WEB_DIR.glob("*.js"))
        for key in re.findall(r"(?:localStorage|sessionStorage)\.setItem\(([^,]+),", path.read_text(encoding="utf-8"))
    ]
    assert stored == [("app.js", "MIC_SEEN_KEY")]
    for path in sorted(WEB_DIR.glob("*.js")):
        source = path.read_text(encoding="utf-8")
        assert "indexedDB" not in source and "new MediaRecorder" not in source, path.name


def test_the_client_never_logs_to_the_console():
    for path in sorted(WEB_DIR.glob("*.js")):
        assert "console." not in path.read_text(encoding="utf-8"), path.name
