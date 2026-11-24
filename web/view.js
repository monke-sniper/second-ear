/*
 * Second Ear — the screen. Draws the five components in docs/design/components/:
 * RiskMeter, the transcript lines, AlertSheet, SafeExitCard, OfficialNumberCard,
 * DangerBanner. In: plain values from server events. Out: DOM state.
 * It opens no socket, touches no audio, and holds no copy: text comes from `t`.
 */

const el = (id) => document.getElementById(id);

const CIRCLE = "●";
const TRIANGLE = "▲";
const SQUARE = "■";
// Display-only bands (risk-meter.md). The alert rules live on the server.
const BANDS = [
  { name: "scam", from: 85, shape: SQUARE, word: "meter_scam" },
  { name: "watch", from: 50, shape: TRIANGLE, word: "meter_watch" },
  { name: "calm", from: 0, shape: CIRCLE, word: "meter_calm" },
];
const NEUTRAL = { name: "neutral", shape: CIRCLE, word: "meter_real_call" };
const TRANSCRIPT_LINES = 2;
const SAFE_EXIT_MAX_LINES = 3;
// The sizes the line to say steps down through, largest first (safe-exit-card.md).
const LINE_STEPS = ["safe-exit__line--title", "safe-exit__line--small"];

const START = { score: 0, lines: [], sheet: null, explainer: null, source: null, realCall: false };
let state = START;
let t = (key) => key;

/** Fill every `data-copy` element from the dictionary and draw the empty state. */
export function initView(translate) {
  t = translate;
  document.querySelectorAll("[data-copy]").forEach((node) => {
    node.textContent = t(node.dataset.copy);
  });
  document.querySelectorAll("[data-copy-label]").forEach((node) => {
    node.setAttribute("aria-label", t(node.dataset.copyLabel));
  });
  // The sheet starts below the banner, however tall the banner's text runs.
  new ResizeObserver(() => {
    const height = el("danger-banner").offsetHeight;
    document.documentElement.style.setProperty("--banner-height", `${height}px`);
  }).observe(el("danger-banner"));
  resetView();
}

/** A new call: nothing heard, no alert, no banner, the meter at calm zero. */
export function resetView() {
  state = START;
  closeSheet();
  paintBanner(false);
  el("real-call-note").hidden = true;
  paintMeter();
  paintTranscript();
}

export function setStatus(key) {
  el("status").textContent = t(key);
}

/** RiskMeter: an integer 0–100, its band, word and shape. No decimals, no animation. */
export function renderRisk(score) {
  if (!Number.isFinite(score)) {
    return;
  }
  state = { ...state, score: Math.max(0, Math.min(100, Math.round(score * 100))) };
  paintMeter();
}

function paintMeter() {
  const band = state.realCall ? NEUTRAL : BANDS.find((entry) => state.score >= entry.from);
  const word = t(band.word);
  const meter = el("risk-meter");
  meter.dataset.band = band.name;
  meter.setAttribute("aria-valuenow", String(state.score));
  meter.setAttribute("aria-valuetext", t("meter_value_text", { word, score: state.score }));
  el("risk-shape").textContent = band.shape;
  el("risk-word").textContent = word;
  el("risk-score").textContent = String(state.score);
  el("risk-fill").style.width = `${state.score}%`;
}

/** Keep the last two chunks. The server has already replaced every number. */
export function renderTranscript(text) {
  if (typeof text !== "string" || text.trim() === "") {
    return;
  }
  state = { ...state, lines: [...state.lines, text].slice(-TRANSCRIPT_LINES) };
  paintTranscript();
}

/** The call is over: back to the placeholder, so no words from it stay on the screen. */
export function clearTranscript() {
  state = { ...state, lines: [] };
  paintTranscript();
}

function paintTranscript() {
  const lines = state.lines.length > 0 ? state.lines : [t("transcript_empty")];
  const nodes = lines.map((line) => {
    const node = document.createElement("p");
    node.className = "transcript__line";
    node.textContent = line;
    return node;
  });
  el("transcript").replaceChildren(...nodes);
}

/** Open the AlertSheet, or rewrite it in place when caution becomes scam. */
export function renderAlert(level) {
  const isKnown = level === "caution" || level === "scam";
  if (!isKnown || state.realCall || state.sheet === "scam") {
    return; // marked as a real call, or already at the top level
  }
  const wasOpen = state.sheet !== null;
  state = { ...state, sheet: level };
  const isScam = level === "scam";
  el("alert-sheet").dataset.level = level;
  el("alert-shape").textContent = isScam ? SQUARE : TRIANGLE;
  el("alert-title").textContent = t(isScam ? "alert_scam_title" : "alert_caution_title");
  if (!wasOpen) {
    el("alert-scrim").hidden = false;
    el("app").inert = true;
    document.body.classList.add("is-locked");
  }
  paintCards();
  if (!wasOpen) {
    el("alert-title").focus();
  }
}

/**
 * Late enrichment. A degraded answer changes nothing: what is on screen stays.
 * `source` is the copy key saying where this page's model wrote the answer, on the
 * device or in the cloud; null when the server's own explainer wrote it.
 */
export function renderExplainer(event, source = null) {
  if (!event || event.degraded === true || typeof event.safe_exit_line !== "string") {
    return;
  }
  state = { ...state, explainer: event, source };
  if (state.sheet !== null) {
    paintCards();
  }
}

function paintCards() {
  const info = state.explainer;
  const line = el("safe-exit-line");
  line.textContent = info !== null && info.safe_exit_line.trim() !== ""
    ? info.safe_exit_line
    : t("safe_exit_default");
  // Never truncated: a line that runs past three lines steps down, to title size and
  // then to 28 px, and stops at the first size that fits.
  line.classList.remove(...LINE_STEPS);
  for (const step of LINE_STEPS) {
    const lineHeight = parseFloat(getComputedStyle(line).lineHeight);
    if (line.clientHeight <= lineHeight * SAFE_EXIT_MAX_LINES + 1) {
      break;
    }
    line.classList.remove(...LINE_STEPS);
    line.classList.add(step);
  }
  paintOfficial(info);
  paintSource();
}

/** Where the line was written. Last in the sheet, so it never pushes the line to say,
 *  the number to call or the button down the screen. */
function paintSource() {
  const note = el("explainer-source");
  note.textContent = state.source !== null ? t(state.source) : "";
  note.hidden = state.source === null;
}

/** A number is shown only if the server sent one; nothing is ever guessed here. */
function paintOfficial(info) {
  const org = info !== null && typeof info.org_name === "string" ? info.org_name : "";
  const sent = info !== null && typeof info.official_number === "string" ? info.official_number : "";
  const number = org !== "" ? sent : "";
  const link = el("official-number");
  el("official-org").textContent = org;
  el("official-org").hidden = org === "";
  el("official-fallback").hidden = number !== "";
  link.textContent = number;
  link.hidden = number === "";
  link.removeAttribute("href");
  link.removeAttribute("aria-label");
  if (number !== "" && window.matchMedia("(pointer: coarse)").matches) {
    link.setAttribute("href", `tel:${number.replace(/[^\d+]/g, "")}`);
    link.setAttribute("aria-label", t("call_number_label", { org, number }));
  }
}

/** The code warning: one banner, its two fixed lines, no count and never the digits.
 *  Shown once and never re-announced; it stays until reset. */
export function renderDanger() {
  if (!el("danger-banner").hidden) {
    return; // already up: it was said once
  }
  paintBanner(true);
}

/** The banner's two lines are written when it shows and emptied when it hides. A screen
 *  reader announces a live region when its text changes; words that have sat in a hidden
 *  element since the page loaded are not a change, so they could go unsaid. */
function paintBanner(isShown) {
  const banner = el("danger-banner");
  banner.hidden = !isShown;
  banner.querySelectorAll("[data-copy]").forEach((node) => {
    node.textContent = isShown ? t(node.dataset.copy) : "";
  });
}

/** "This is a real call": sheet closed, meter neutral. The banner is not touched. */
export function markRealCall() {
  state = { ...state, sheet: null, realCall: true };
  closeSheet();
  el("real-call-note").hidden = false;
  paintMeter();
  const next = ["stop", "demo-play", "start"].map(el).find((node) => !node.hidden);
  if (next) {
    next.focus();
  }
}

/** The call ended with the sheet up: close it, so the page behind it works again.
 *  Returns whether a sheet was open. */
export function closeAlert() {
  const wasOpen = state.sheet !== null;
  state = { ...state, sheet: null };
  closeSheet();
  return wasOpen;
}

function closeSheet() {
  el("alert-scrim").hidden = true;
  el("app").inert = false;
  document.body.classList.remove("is-locked");
}
