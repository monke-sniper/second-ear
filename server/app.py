"""The FastAPI app: health, the audio socket, the simulate endpoint, the static app.

It wires modules together and owns per-connection state. It does not transcribe,
score, decide, explain, or push — each of those lives in its own module.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from server.config import WEB_DIR
from server.contracts import AudioAck, ErrorEvent, SimulateRequest, SimulateResponse

log = logging.getLogger("second_ear.app")


def create_app() -> FastAPI:
    app = FastAPI(title="Second Ear", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness for the demo laptop and for anyone who checks out the repo."""
        return {"status": "ok"}

    @app.websocket("/ws/audio")
    async def audio_socket(ws: WebSocket) -> None:
        """Phase 1: accept bytes, count them, ack.

        Phase 3 replaces the body with the real pipeline (chunker → stt → scorer →
        alerts → danger → explainer → notify). The ack stays: it is the cheapest
        proof that the socket and the browser's mic path work before Whisper is
        involved, and it is the first thing to check when a demo goes quiet.
        """
        await ws.accept()
        total = 0
        try:
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                data = message.get("bytes")
                if data is not None:
                    total += len(data)
                    ack = AudioAck(bytes=len(data), total=total)
                    await ws.send_json(ack.model_dump(mode="json"))
                    continue
                text = (message.get("text") or "").strip()
                err = ErrorEvent(detail=f"event not handled yet: {text[:80]}")
                await ws.send_json(err.model_dump(mode="json"))
        except WebSocketDisconnect:
            pass
        finally:
            log.info("audio socket closed after %d bytes", total)

    @app.post("/simulate", response_model=SimulateResponse)
    def simulate(request: SimulateRequest) -> SimulateResponse:
        """Replay text chunks through the live pipeline, no mic and no audio.

        Declared now because phase 3, phase 4 and phase 6 all call it, and its shape
        is the contract. The body lands in phase 3.
        """
        raise HTTPException(status_code=501, detail="pipeline lands in phase 3 — docs/SPEC.md §3")

    # Mounted last so the routes above win; html=True serves index.html at "/".
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
