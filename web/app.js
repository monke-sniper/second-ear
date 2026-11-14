/*
 * Second Ear — browser client.
 *
 * Owns: mic capture through an AudioWorklet, the /ws/audio socket, and turning
 * server events into DOM state. It does not score, decide, or talk to Anthropic;
 * all of that is server-side. The elements below match docs/design/screens.md.
 *
 * Scaffold only: every function is declared, none is implemented. Phase 3 fills
 * capture + socket, Phase 5 fills the rendering.
 */

export const WS_URL = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/audio`;

const el = (id) => document.getElementById(id);

/* ---------------------------------------------------------------- server events */

/** RiskMeter update. `level` is "none" | "caution" | "scam". */
export function renderRisk(score, level) {
  // TODO(phase 5): band per docs/design/components/risk-meter.md
}

/** Append one final chunk to the transcript block; keep the last two lines. */
export function renderTranscript(text) {
  // TODO(phase 5)
}

/** Open the AlertSheet (SafeExitCard + OfficialNumberCard). */
export function renderAlert(event) {
  // TODO(phase 5): level → header colour, word and shape
}

/** Late enrichment for the open alert; may arrive after the sheet is visible. */
export function renderExplainer(event) {
  // TODO(phase 5): safe-exit line, org, number, degraded copy
}

/** The code warning. Never shows digits. */
export function renderDanger(event) {
  // TODO(phase 5): show the banner, keep it until reset
}

/** "This is a real call": close the sheet, neutralise the meter, keep the banner armed. */
export function markRealCall() {
  // TODO(phase 5)
}

function handleServerEvent(event) {
  // TODO(phase 3): switch (event.type) over the shapes in server/contracts.py
}

/* -------------------------------------------------------------- audio pipeline */

/** Ask for the mic, load the worklet, start the socket. Phase 3. */
export async function startCall() {
  throw new Error("mic capture lands in phase 3 — see docs/SPEC.md §3");
}

/** Stop the tracks, close the socket, flush the last chunk. Phase 3. */
export function stopCall() {
  throw new Error("mic capture lands in phase 3 — see docs/SPEC.md §3");
}

/** Open /ws/audio and route JSON events to handleServerEvent. Phase 3. */
export function connectAudioSocket() {
  // TODO(phase 3): new WebSocket(WS_URL), binaryType = "arraybuffer"
}

/* -------------------------------------------------------------------- bindings */

// TODO(phase 5): bind #start, #stop, #demo, #real-call. Demo mode streams
// eval/calls/demo_scam.wav through the same pipeline with the mic off.
