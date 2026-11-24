"""The FastAPI app: health, the audio socket, simulate, the page's explainer config, the
demo recording, the static app.

It builds the shared services and hands each request to the module that owns it.
It does not transcribe, score, decide, explain, or push — each of those lives in its
own module, and the socket's per-call work lives in live.py.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Response, WebSocket, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server import pipeline
from server.config import CALLS_DIR, WEB_DIR, FirebaseSettings, get_settings
from server.contracts import PageExplainerConfig, SimulateRequest, SimulateResponse
from server.demo import find_demo_audio
from server.explainer import Explainer
from server.live import LiveCall, Services, Transcriber
from server.notify import NtfyNotifier
from server.page_explainer import page_config
from server.scorer import RiskScorer, load_app_scorer
from server.stt import load_transcriber

log = logging.getLogger("second_ear.app")

# The only pages that may open the audio socket: the app, served from this machine.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


def origin_allowed(origin: str | None) -> bool:
    """True when a socket handshake may go ahead.

    A browser always sends Origin with a WebSocket handshake and a page cannot change
    it, so any page on another site is refused here: it could otherwise open a socket
    to localhost, feed it audio and set off a push. A client that sends no Origin is
    not a browser (the tests, a script on this machine) and is let in.
    """
    if origin is None:
        return True
    try:
        host = urlsplit(origin).hostname
    except ValueError:
        return False
    return host in LOCAL_HOSTS


def warm_up(services: Services) -> None:
    """Pay the slow first loads before the first chunk needs them.

    Runs in its own thread at startup. A failure is logged and nothing else: the
    server still answers, and the first chunk will try the load again.
    """
    try:
        services.transcriber.warmup()
    except Exception as exc:
        log.warning("whisper warmup failed: %s", type(exc).__name__)
    ensure_loaded = getattr(services.scorer, "ensure_loaded", None)
    if not callable(ensure_loaded):
        return
    try:
        ensure_loaded()
    except Exception as exc:
        log.warning("scorer load failed: %s", type(exc).__name__)


def create_app(
    transcriber: Transcriber | None = None,
    scorer: RiskScorer | None = None,
    explainer: Explainer | None = None,
    notifier_factory: Callable[[], NtfyNotifier] | None = None,
    calls_dir: Path | None = None,
    firebase: FirebaseSettings | None = None,
) -> FastAPI:
    """Build the app. Every argument is a seam for tests; the defaults are the real
    Whisper, the trained scorer or its stand-in, Haiku, ntfy from .env, the recordings
    folder, and the Firebase web app named in .env (none: the page is never asked to
    explain)."""
    recordings = calls_dir if calls_dir is not None else CALLS_DIR
    page_firebase = firebase if firebase is not None else get_settings().firebase
    services = Services(
        transcriber=transcriber if transcriber is not None else load_transcriber(),
        scorer=scorer if scorer is not None else load_app_scorer(),
        explainer=explainer if explainer is not None else Explainer(),
        notifier_factory=notifier_factory if notifier_factory is not None else NtfyNotifier,
        ask_page=page_firebase is not None,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        threading.Thread(target=warm_up, args=(services,), name="warmup", daemon=True).start()
        yield

    app = FastAPI(title="Second Ear", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness for the demo laptop and for anyone who checks out the repo."""
        return {"status": "ok"}

    @app.websocket("/ws/audio")
    async def audio_socket(ws: WebSocket) -> None:
        """Bytes in, events out. The ack per frame stays: it is the cheapest proof that
        the socket and the browser's mic path work, and the first thing to check when
        a demo goes quiet. A page from another site is refused before the handshake
        completes (docs/SPEC.md §3)."""
        if not origin_allowed(ws.headers.get("origin")):
            log.warning("audio socket refused: the page is not served from this machine")
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await ws.accept()
        await LiveCall(ws, services).run()

    @app.post("/simulate", response_model=SimulateResponse)
    def simulate(request: SimulateRequest) -> SimulateResponse:
        """Replay text chunks through the live pipeline, no mic and no audio.

        Same session, same rules and the same explainer as the socket. It never
        sends a push.
        """
        return pipeline.simulate(request, services.scorer, services.explainer)

    @app.get("/explainer/config", response_model=PageExplainerConfig, response_model_exclude_none=True)
    def explainer_config(response: Response) -> PageExplainerConfig:
        """What the page needs to make the explainer's model call through Firebase AI
        Logic: the web app's config, the cloud model, the instructions and the answer's
        JSON schema. Without Firebase in .env it says so, and the page loads no SDK."""
        response.headers["Cache-Control"] = "no-store"
        return page_config(page_firebase, services.explainer)

    @app.get("/demo/audio")
    def demo_audio() -> FileResponse:
        """The recording demo mode replays: the recorded call, else the synthetic one.

        The file name rides in Content-Disposition so the console can say which of
        the two it is playing. Neither file there is a 404, never an error page.
        """
        path = find_demo_audio(recordings)
        if path is None:
            raise HTTPException(status_code=404, detail="no demo recording")
        return FileResponse(
            path,
            media_type="audio/wav",
            filename=path.name,
            content_disposition_type="inline",
            headers={"Cache-Control": "no-store"},
        )

    # Mounted last so the routes above win; html=True serves index.html at "/".
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
