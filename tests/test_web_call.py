"""The client's half of two socket rules, read as text.

The browser code has no test runner, so these read `web/` the way test_web_copy.py
does. They pin that the code is there, not that a browser runs it.
"""

from __future__ import annotations

import re

from server.config import WEB_DIR
from server.contracts import FRAME_BYTES, FRAME_MS

APP_JS = (WEB_DIR / "app.js").read_text(encoding="utf-8")
CALL_JS = (WEB_DIR / "call.js").read_text(encoding="utf-8")


def js_constant(source: str, name: str) -> int:
    found = re.search(rf"^const {name} = (\d+);", source, flags=re.MULTILINE)
    assert found is not None, f"{name} is not defined"
    return int(found.group(1))


def test_stopping_a_call_sends_a_second_of_quiet_before_the_socket_closes():
    stop = CALL_JS.split("export function stopCall()", 1)[1]

    assert js_constant(CALL_JS, "FRAME_BYTES") == FRAME_BYTES
    assert js_constant(CALL_JS, "STOP_SILENCE_FRAMES") * FRAME_MS == 1000
    assert "socket.send(new ArrayBuffer(FRAME_BYTES))" in stop
    assert stop.index("socket.send(") < stop.index("socket.close()")


def test_a_server_error_is_shown_in_the_status_line():
    # The server sends one when Whisper fails; the screen must not stay on "Listening."
    handler = APP_JS.split('case "error":', 1)[1].split("return;", 1)[0]

    assert 'view.setStatus("status_audio_error")' in handler
    assert re.search(r"^\s{4}status_audio_error:", APP_JS, flags=re.MULTILINE) is not None
