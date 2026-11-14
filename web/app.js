/*
 * Second Ear — browser client entry point.
 * Owns: every word on the screen (one dictionary), the routing of server events to
 * the view, and the Start / Stop / "This is a real call" / Demo buttons.
 * It does not score, decide or explain: the server does. Audio lives in call.js,
 * drawing in view.js, the demo console in demo.js.
 */

import { micSupported, startMicCall, stopCall } from "./call.js";
import { initDemo } from "./demo.js";
import * as view from "./view.js";

/*
 * All copy, by key. Strings marked in docs/design/ are fixed: they are the readable
 * half of the safety feature. Spanish is a second block here, not a layout change.
 */
export const COPY = {
  en: {
    app_title: "Second Ear",
    status_ready: "Put the call on speaker next to this phone.",
    status_starting: "Starting.",
    status_listening: "Listening.",
    status_stopped: "Stopped.",
    status_mic_blocked:
      "The microphone is blocked. Allow it in the browser, then press Start listening.",
    status_no_mic: "No microphone was found.",
    status_insecure: "The microphone only works on localhost or https.",
    status_lost: "The connection dropped. Press Start listening to try again.",
    status_audio_error: "Some audio could not be read. Still listening.",
    mic_note: "The browser will ask to use the microphone. Choose Allow.",
    start: "Start listening",
    stop: "Stop",
    demo_mode: "Demo mode",
    transcript_label: "Live transcript",
    transcript_empty: "The call will appear here.",
    meter_label: "Scam risk",
    meter_calm: "Calm",
    meter_watch: "Watch",
    meter_scam: "Scam",
    meter_real_call: "Real call",
    meter_value_text: "{word}, {score} out of 100",
    real_call_note: "Marked as a real call. Alerts are off for this call.",
    alert_caution_title: "Be careful",
    alert_scam_title: "This sounds like a scam",
    say_this: "SAY THIS",
    safe_exit_default: "I'll call you back at the number on my card.",
    call_back: "CALL BACK",
    call_back_fallback: "Use the number on your card or your last statement.",
    call_number_label: "Call {org} at {number}",
    real_call: "This is a real call",
    danger_title: "Do not read that number out",
    danger_body: "Hang up, then call back on a number you know.",
    demo_play: "Play",
    demo_replay: "Replay",
    demo_label_recorded: "Recorded call, replayed through the same pipeline.",
    demo_label_synthetic: "Synthetic voice, replayed through the same pipeline.",
    demo_text_replay: "Text replay, no audio",
    demo_footer: "Nothing here is live. The mic is off in demo mode.",
    demo_ready: "Press Play to start the replay.",
    demo_playing: "Playing.",
    demo_catching_up: "Checking the last few seconds.",
    demo_finished: "The replay has ended.",
    demo_failed: "The replay could not start.",
    demo_lost: "The connection dropped. Press Replay to try again.",
    timeline_first_alert: "First alert at {seconds} seconds.",
  },
};
const LANGUAGE = "en";
const DEMO_PARAM = "demo";
const MIC_SEEN_KEY = "second-ear-mic-explained";
const MIC_ERRORS = {
  NotAllowedError: "status_mic_blocked",
  SecurityError: "status_mic_blocked",
  NotFoundError: "status_no_mic",
  OverconstrainedError: "status_no_mic",
};

const el = (id) => document.getElementById(id);

/** The copy for `key`, with `{name}` slots filled from `values`. */
export function t(key, values = {}) {
  const template = COPY[LANGUAGE][key];
  if (template === undefined) {
    return key;
  }
  return template.replace(/\{(\w+)\}/g, (_slot, name) => String(values[name] ?? ""));
}

/** One server event in, one change on screen. Shapes are server/contracts.py. */
export function handleServerEvent(event) {
  if (event === null || typeof event !== "object") {
    return;
  }
  switch (event.type) {
    case "ack": // proof that frames arrive; there is nothing to draw
      return;
    case "transcript":
      view.renderTranscript(event.text);
      return;
    case "risk":
      view.renderRisk(event.score);
      return;
    case "alert":
      view.renderAlert(event.level);
      return;
    case "explainer":
      view.renderExplainer(event);
      return;
    case "danger": // the event carries a count for eval; the screen does not show it
      view.renderDanger();
      return;
    case "error": // the server's own text stays off the screen
      view.setStatus("status_audio_error");
      return;
    default:
      return;
  }
}

/** Which controls belong to which screen (docs/design/screens.md). */
function setScreen(name) {
  el("app").dataset.screen = name;
  el("start").hidden = name !== "ready";
  el("demo").hidden = name !== "ready";
  el("stop").hidden = name !== "listening";
  ["demo-card", "timeline", "timeline-note", "demo-foot"].forEach((id) => {
    el(id).hidden = name !== "demo";
  });
  el("mic-note").hidden = name !== "ready" || micWasExplained();
}

function micWasExplained() {
  try {
    return localStorage.getItem(MIC_SEEN_KEY) === "1";
  } catch {
    return false; // storage is blocked; showing the line again does no harm
  }
}

function rememberMicExplained() {
  try {
    localStorage.setItem(MIC_SEEN_KEY, "1");
  } catch {
    // storage is blocked; the line simply shows again next time
  }
}

async function onStart() {
  if (!micSupported()) {
    view.setStatus("status_insecure");
    return;
  }
  el("start").disabled = true;
  view.resetView();
  view.setStatus("status_starting");
  try {
    await startMicCall({ onEvent: handleServerEvent, onClose: onLost });
    rememberMicExplained();
    setScreen("listening");
    view.setStatus("status_listening");
  } catch (error) {
    const name = error instanceof Error ? error.name : "";
    view.setStatus(MIC_ERRORS[name] || "status_lost");
  }
  el("start").disabled = false;
}

function onStop() {
  stopCall();
  setScreen("ready");
  view.setStatus("status_stopped");
}

function onLost() {
  stopCall();
  setScreen("ready");
  view.setStatus("status_lost");
}

function boot() {
  view.initView(t);
  el("start").addEventListener("click", onStart);
  el("stop").addEventListener("click", onStop);
  el("real-call").addEventListener("click", view.markRealCall);
  el("demo").addEventListener("click", () => location.assign(`?${DEMO_PARAM}=1`));
  if (new URLSearchParams(location.search).get(DEMO_PARAM) === "1") {
    setScreen("demo");
    initDemo({ onEvent: handleServerEvent, onReset: view.resetView, setStatus: view.setStatus, t });
    return;
  }
  setScreen("ready");
  view.setStatus("status_ready");
}

boot();
