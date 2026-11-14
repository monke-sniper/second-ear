/*
 * Second Ear — demo console (screen 6, /?demo=1).
 * Replays a recording through the same worklet and socket as a live call, out loud,
 * with the mic off. If the server has no recording it replays a scripted call
 * through /simulate instead. It never asks for the mic and draws no alert itself:
 * every event goes to the handler the live call uses.
 */

import { bytesSent, startRecordingCall, stopCall } from "./call.js";

const AUDIO_URL = "demo/audio";
const SIMULATE_URL = "simulate";
const SYNTHETIC_FILE = "tts_scam.wav";
const FILE_NAME = /filename="([^"]+)"/;
// Silence sent after the recording, so the server closes the last chunk (6 s at most,
// docs/SPEC.md §2). The replay then waits until the server has acked all of it: a slow
// Whisper can run many seconds behind, and the last alert must not be cut off.
const FLUSH_MS = 6500;
const EXPLAINER_MS = 4500; // the explainer's 4 s budget, and a little
const MAX_CATCH_UP_MS = 60000;
const TICK_MS = 250;
const CHUNK_SECONDS = 4.0;
const REPLAY_SPEED = 2; // the text replay runs at twice the call's pace
const EXPLAINER_DELAY_MS = 600;

// A made-up grandparent scam. `show` is what the server would put on the wire.
const SCRIPT = [
  { say: "Hi grandma, it's me, your grandson." },
  { say: "I'm in trouble. I was in an accident and I'm in jail right now." },
  { say: "Please don't tell mom. I need you to help me with bail today." },
  { say: "My lawyer says you have to buy gift cards right away." },
  { say: "Read me the code on the back of the gift card." },
  { say: "four seven two nine one one three eight five zero six two", show: "[number]" },
];

const el = (id) => document.getElementById(id);

let app = null; // { onEvent, onReset, setStatus, t }
let recording = null; // { name, bytes }, or null when the server has none
let run = { timers: [], startedAt: 0, durationMs: 0, marked: false, acked: 0 };

/** Find out what there is to replay, label it, and arm the Play button. */
export async function initDemo(hooks) {
  app = hooks;
  recording = await fetchRecording();
  if (recording === null) {
    el("demo-file").textContent = app.t("demo_text_replay");
    el("demo-label").hidden = true;
  } else {
    const isSynthetic = recording.name === SYNTHETIC_FILE;
    el("demo-file").textContent = recording.name;
    el("demo-label").textContent = app.t(isSynthetic ? "demo_label_synthetic" : "demo_label_recorded");
  }
  el("demo-play").addEventListener("click", play);
  el("demo-play").disabled = false;
  app.setStatus("demo_ready");
}

async function fetchRecording() {
  try {
    const response = await fetch(AUDIO_URL);
    if (!response.ok) {
      return null;
    }
    const named = FILE_NAME.exec(response.headers.get("Content-Disposition") || "");
    return { name: named ? named[1] : "", bytes: await response.arrayBuffer() };
  } catch {
    return null; // no recording to be had; the text replay still works
  }
}

async function play() {
  const button = el("demo-play");
  button.disabled = true;
  endRun();
  app.onReset();
  el("timeline-fill").style.width = "0%";
  el("timeline-mark").hidden = true;
  el("timeline-note").textContent = "";
  try {
    const durationMs = recording === null ? await playScript() : await playRecording();
    run = { ...run, startedAt: performance.now(), durationMs, marked: false };
    run.timers.push(setInterval(tick, TICK_MS));
    app.setStatus("demo_playing");
  } catch {
    endRun();
    app.setStatus("demo_failed");
  }
  button.textContent = app.t("demo_replay");
  button.disabled = false;
}

/** Audio path: the same samples go to the speakers and to the socket. */
async function playRecording() {
  const seconds = await startRecordingCall(recording.bytes, {
    onEvent: relay,
    onClose: lost,
    onEnded: () => run.timers.push(setTimeout(waitForServer, FLUSH_MS)),
  });
  return seconds * 1000;
}

/** The audio is all sent. End the replay once the server has heard all of it. */
function waitForServer() {
  const needed = bytesSent();
  const since = performance.now();
  app.setStatus("demo_catching_up");
  const poll = setInterval(() => {
    const caughtUp = run.acked >= needed;
    if (!caughtUp && performance.now() - since < MAX_CATCH_UP_MS) {
      return;
    }
    clearInterval(poll);
    run.timers.push(setTimeout(finish, caughtUp ? EXPLAINER_MS : 0));
  }, TICK_MS);
  run.timers.push(poll);
}

/** Text path: one POST to /simulate, then its events replayed on a timer. */
async function playScript() {
  const response = await fetch(SIMULATE_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chunks: SCRIPT.map((line) => line.say), chunk_seconds: CHUNK_SECONDS }),
  });
  if (!response.ok) {
    throw new Error("simulate failed");
  }
  const scheduled = scriptEvents(await response.json());
  scheduled.forEach(({ atMs, event }) => run.timers.push(setTimeout(relay, atMs, event)));
  const lastMs = Math.max(...scheduled.map((entry) => entry.atMs));
  run.timers.push(setTimeout(finish, lastMs + TICK_MS));
  return (SCRIPT.length * CHUNK_SECONDS * 1000) / REPLAY_SPEED;
}

/** The simulate answer as socket-shaped events, in the order the socket sends them. */
function scriptEvents(result) {
  const at = (event, extraMs = 0) => ({ atMs: (event.t_s * 1000) / REPLAY_SPEED + extraMs, event });
  const spoken = result.timeline.flatMap((point, index) => {
    const line = SCRIPT[index];
    const text = line.show !== undefined ? line.show : line.say;
    return [at({ type: "transcript", text, t_s: point.t_s }), at({ type: "risk", ...point })];
  });
  const late = result.explainers.map((event) => at(event, EXPLAINER_DELAY_MS));
  // sort() is stable, so events at the same moment keep this order.
  return [...spoken, ...result.alerts.map((e) => at(e)), ...result.danger.map((e) => at(e)), ...late]
    .sort((a, b) => a.atMs - b.atMs);
}

/** Pass an event on, and pin the first alert to the timeline on the way. */
function relay(event) {
  if (event.type === "ack" && Number.isFinite(event.total)) {
    run = { ...run, acked: event.total };
  }
  if (event.type === "alert" && !run.marked && run.durationMs > 0) {
    run = { ...run, marked: true };
    const speed = recording === null ? REPLAY_SPEED : 1;
    const share = Math.min(1, (event.t_s * 1000) / speed / run.durationMs);
    el("timeline-mark").style.left = `${share * 100}%`;
    el("timeline-mark").hidden = false;
    el("timeline-note").textContent = app.t("timeline_first_alert", { seconds: Math.round(event.t_s) });
  }
  app.onEvent(event);
}

function tick() {
  const share = Math.min(1, (performance.now() - run.startedAt) / run.durationMs);
  el("timeline-fill").style.width = `${share * 100}%`;
}

function finish() {
  endRun();
  el("timeline-fill").style.width = "100%";
  app.setStatus("demo_finished");
}

/** The socket closed under the replay. */
function lost() {
  endRun();
  app.setStatus("demo_lost");
}

/** Stop the timers and the call. What is on screen stays until the next Play. */
function endRun() {
  run.timers.forEach((timer) => clearTimeout(timer)); // clears intervals too
  run = { timers: [], startedAt: 0, durationMs: 0, marked: false, acked: 0 };
  stopCall();
}
