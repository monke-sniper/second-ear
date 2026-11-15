"""The WebSocket contract: bytes in, counted acks out.

This is the Phase 1 proof, and the first thing to re-run when a demo goes quiet:
if the ack stops, the problem is the mic or the socket, not Whisper.
"""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

from server.app import origin_allowed
from tests.helpers import silence_frame


def test_ack_counts_each_frame_and_the_total(client):
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_bytes(silence_frame())
        assert ws.receive_json() == {"type": "ack", "bytes": 8000, "total": 8000}

        ws.send_bytes(silence_frame())
        assert ws.receive_json() == {"type": "ack", "bytes": 8000, "total": 16000}


def test_short_frame_is_accepted_and_counted(client):
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_bytes(b"\x00\x00" * 400)  # 50 ms, e.g. a partial frame
        assert ws.receive_json() == {"type": "ack", "bytes": 800, "total": 800}


def test_unknown_text_event_returns_an_error_not_a_disconnect(client):
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_text('{"type": "hangup"}')
        message = ws.receive_json()
        assert message["type"] == "error"
        assert "hangup" in message["detail"]

        ws.send_bytes(silence_frame())  # the socket is still open
        assert ws.receive_json()["type"] == "ack"


def test_an_error_never_echoes_what_the_client_sent(client):
    with client.websocket_connect("/ws/audio") as ws:
        for text in ("not json", '{"type": "4111 1111 1111 1111"}', "[1, 2]"):
            ws.send_text(text)
            assert ws.receive_json() == {"type": "error", "detail": "event not handled: unknown"}


def test_reset_restarts_the_ack_total(client):
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_bytes(silence_frame())
        ws.send_bytes(silence_frame())
        assert ws.receive_json()["total"] == 8000
        assert ws.receive_json()["total"] == 16000

        ws.send_text('{"type": "reset"}')  # handled, and it sends nothing back
        ws.send_bytes(silence_frame())
        assert ws.receive_json() == {"type": "ack", "bytes": 8000, "total": 8000}


def test_a_frame_over_64_kib_is_refused_and_not_counted(client):
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_bytes(b"\x00" * (64 * 1024 + 2))
        assert ws.receive_json() == {"type": "error", "detail": "audio frame too large"}

        ws.send_bytes(silence_frame())
        assert ws.receive_json() == {"type": "ack", "bytes": 8000, "total": 8000}


def test_a_page_on_another_site_cannot_open_the_audio_socket(client):
    # Any site can try a WebSocket to localhost; the browser says where the page is from.
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/ws/audio", headers={"Origin": "https://evil.example"}):
            pass
    assert refused.value.code == 1008


@pytest.mark.parametrize(
    "origin", ["http://localhost:8000", "http://127.0.0.1:8000", "https://localhost"]
)
def test_the_apps_own_page_can_open_the_audio_socket(client, origin):
    with client.websocket_connect("/ws/audio", headers={"Origin": origin}) as ws:
        ws.send_bytes(silence_frame())
        assert ws.receive_json() == {"type": "ack", "bytes": 8000, "total": 8000}


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "http://localhost.evil.example",
        "http://evil.example/?localhost",
        "http://127.0.0.1.evil.example:8000",
        "http://192.168.1.20:8000",
        "null",  # a sandboxed frame, or a file opened from disk
        "",
        "http://[",  # not a URL at all
    ],
)
def test_only_localhost_and_127_0_0_1_are_local(origin):
    assert origin_allowed(origin) is False


def test_a_client_that_sends_no_origin_is_not_a_browser_and_is_let_in():
    assert origin_allowed(None) is True
