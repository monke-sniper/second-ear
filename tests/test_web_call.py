"""The client's half of the call's rules, read as text.

The browser code has no test runner, so these read `web/` the way test_web_copy.py
does. They pin that the code is there, not that a browser runs it.
"""

from __future__ import annotations

import re

from server.config import WEB_DIR
from server.contracts import FRAME_BYTES, FRAME_MS

APP_JS = (WEB_DIR / "app.js").read_text(encoding="utf-8")
CALL_JS = (WEB_DIR / "call.js").read_text(encoding="utf-8")
VIEW_JS = (WEB_DIR / "view.js").read_text(encoding="utf-8")


def function_body(source: str, signature: str) -> str:
    """The text of one top-level function, from its signature to its closing brace."""
    assert signature in source, f"{signature} is not defined"
    return source.split(signature, 1)[1].split("\n}\n", 1)[0]


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


def test_ending_a_call_clears_the_transcript_back_to_the_placeholder():
    # Stop and a dropped connection both end the call. Nothing it said may stay on screen.
    clear = function_body(VIEW_JS, "export function clearTranscript()")
    assert "lines: []" in clear and "paintTranscript()" in clear
    paint = function_body(VIEW_JS, "function paintTranscript()")
    assert 'state.lines.length > 0 ? state.lines : [t("transcript_empty")]' in paint

    end = function_body(APP_JS, "function endCall(statusKey)")
    # The clear comes after stopCall(), which unhooks the socket: no late line can follow it.
    assert end.index("stopCall()") < end.index("view.clearTranscript()")
    assert "socket.onmessage = null" in function_body(CALL_JS, "export function stopCall()")
    assert 'endCall("status_stopped")' in function_body(APP_JS, "function onStop()")
    assert 'endCall("status_lost")' in function_body(APP_JS, "function onLost()")


def test_a_server_error_is_shown_in_the_status_line():
    # The server sends one when Whisper fails; the screen must not stay on "Listening."
    handler = APP_JS.split('case "error":', 1)[1].split("return;", 1)[0]

    assert 'view.setStatus("status_audio_error")' in handler
    assert re.search(r"^\s{4}status_audio_error:", APP_JS, flags=re.MULTILINE) is not None


def test_ending_a_call_closes_the_alert_sheet_so_start_can_be_pressed_again():
    # A connection that drops under an open sheet used to leave the page behind it inert.
    end = function_body(APP_JS, "function endCall(statusKey)")
    assert end.index("stopCall()") < end.index("view.closeAlert()") < end.index('setScreen("ready")')

    close_alert = function_body(VIEW_JS, "export function closeAlert()")
    assert "sheet: null" in close_alert and "closeSheet()" in close_alert
    close_sheet = function_body(VIEW_JS, "function closeSheet()")
    assert 'el("alert-scrim").hidden = true;' in close_sheet
    assert 'el("app").inert = false;' in close_sheet
    assert 'document.body.classList.remove("is-locked");' in close_sheet


def test_a_mic_that_stops_ends_the_call_and_says_so():
    start = function_body(CALL_JS, "export async function startMicCall(handlers)")
    assert "track.onended = () => handlers.onMicEnded();" in start
    assert 'track.readyState === "ended"' in start  # it can stop before the handler is on
    # Stopping the call ourselves must not look like a dead mic.
    stop = function_body(CALL_JS, "export function stopCall()")
    assert stop.index("track.onended = null;") < stop.index("track.stop();")

    assert "onMicEnded }" in function_body(APP_JS, "async function onStart()")
    assert 'endCall("status_mic_stopped")' in function_body(APP_JS, "function onMicEnded()")
    assert 'status_mic_stopped: "The microphone stopped."' in APP_JS
    assert 'MicEndedError: "status_mic_stopped"' in APP_JS


def test_the_danger_banner_gets_its_words_when_it_shows_not_when_the_page_loads():
    # A live region is announced when its text changes, so the text goes in as it appears.
    paint = function_body(VIEW_JS, "function paintBanner(isShown)")
    assert paint.index("banner.hidden = !isShown;") < paint.index("node.textContent =")
    assert 'isShown ? t(node.dataset.copy) : ""' in paint

    assert "paintBanner(true)" in function_body(VIEW_JS, "export function renderDanger()")
    assert "paintBanner(false)" in function_body(VIEW_JS, "export function resetView()")
    # initView fills every data-copy element; the reset at its end empties the hidden banner.
    boot = function_body(VIEW_JS, "export function initView(translate)")
    assert boot.index("node.textContent = t(node.dataset.copy)") < boot.rindex("resetView()")
