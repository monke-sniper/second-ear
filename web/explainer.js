/*
 * Second Ear — the explainer's model call, made by this page through Firebase AI Logic.
 * In: the prompt the server sends with an alert, every number in it already replaced.
 * Out: the model's raw answer and where it ran: Gemini Nano on this device when Chrome
 * has it, cloud Gemini when it does not (hybrid inference, on-device first).
 * It checks nothing and draws nothing: the server validates every answer before any of
 * it reaches the screen. With no Firebase set up it loads no SDK and answers nothing.
 */

// The Firebase JS SDK, straight from Google's CDN: this app has no build step.
const FIREBASE_APP = "https://www.gstatic.com/firebasejs/13.4.0/firebase-app.js";
const FIREBASE_APP_CHECK = "https://www.gstatic.com/firebasejs/13.4.0/firebase-app-check.js";
const FIREBASE_AI = "https://www.gstatic.com/firebasejs/13.4.0/firebase-ai.js";
const CONFIG_URL = "explainer/config";
const JSON_MIME = "application/json";
const LOCAL_HOSTS = ["localhost", "127.0.0.1"];
const ENGLISH_TEXT = [{ type: "text", languages: ["en"] }];
// The longest answer the server reads (server/contracts.py).
const MAX_REPLY_CHARS = 4000;
// Where the model ran, as server/contracts.py spells it. The SDK uses the same two words.
const ON_DEVICE = "on_device";
const IN_CLOUD = "in_cloud";
const NO_ANSWER = { text: "", source: "none" };

/** Firebase, once it is set up: { model, deviceOptions }. Null: the server explains. */
let ready = null;
let loading = null;
/** One idle on-device session, held while a call is on so the model stays loaded. */
let warm = null;
let warmRun = 0;

/**
 * Ask the server whether Firebase is set up and, if it is, load the SDK and build the
 * hybrid model. Resolves true when this page can answer. It never rejects: no network,
 * a blocked CDN or an old browser all mean the server's own explainer answers instead.
 * @returns {Promise<boolean>}
 */
export function loadExplainer() {
  if (loading === null) {
    loading = setUp().then(
      (made) => {
        ready = made;
        return made !== null;
      },
      () => false,
    );
  }
  return loading;
}

async function setUp() {
  const response = await fetch(CONFIG_URL);
  const config = response.ok ? await response.json() : null;
  if (config === null || config.enabled !== true) {
    return null;
  }
  const [appSdk, checkSdk, aiSdk] = await Promise.all([
    import(FIREBASE_APP),
    import(FIREBASE_APP_CHECK),
    import(FIREBASE_AI),
  ]);
  const app = appSdk.initializeApp(config.firebase);
  startAppCheck(app, checkSdk);
  // The on-device model takes its instructions when a session is made; the cloud model
  // takes them as a system instruction. Both get the same words and the same schema.
  const deviceOptions = {
    expectedInputs: ENGLISH_TEXT,
    expectedOutputs: ENGLISH_TEXT,
    initialPrompts: [{ role: "system", content: [{ type: "text", value: config.system }] }],
  };
  const ai = aiSdk.getAI(app, { backend: new aiSdk.GoogleAIBackend() });
  const model = aiSdk.getGenerativeModel(ai, {
    mode: aiSdk.InferenceMode.PREFER_ON_DEVICE,
    inCloudParams: {
      model: config.model,
      systemInstruction: config.system,
      generationConfig: { responseMimeType: JSON_MIME, responseSchema: config.reply_schema },
    },
    onDeviceParams: {
      createOptions: deviceOptions,
      promptOptions: { responseConstraint: config.reply_schema },
    },
  });
  return { model, deviceOptions };
}

/**
 * Firebase AI Logic needs App Check. This page is only ever served from this machine,
 * so it uses App Check's debug provider: the SDK shows a debug token in the browser's
 * developer tools once, and cloud requests pass after that token is registered on the
 * App Check page of the Firebase project. On-device answers need no token at all.
 */
function startAppCheck(app, sdk) {
  if (LOCAL_HOSTS.includes(location.hostname)) {
    self.FIREBASE_APPCHECK_DEBUG_TOKEN = true;
  }
  // Debug mode never asks the provider; anywhere else there is no token to give.
  const provider = new sdk.CustomProvider({
    getToken: () => Promise.reject(new Error("this page has no App Check provider of its own")),
  });
  sdk.initializeAppCheck(app, { provider, isTokenAutoRefreshEnabled: true });
}

/**
 * Make the model call for one alert. Never rejects: a page with no Firebase, or a call
 * that fails, gives the empty answer, and the server shows its fixed line.
 * @param {string} prompt the redacted transcript message from the server
 * @returns {Promise<{ text: string, source: string }>}
 */
export async function answer(prompt) {
  await loading;
  if (ready === null || typeof prompt !== "string") {
    return NO_ANSWER;
  }
  try {
    const result = await ready.model.generateContent(prompt);
    const text = result.response.text();
    if (typeof text !== "string" || text.length > MAX_REPLY_CHARS) {
      return NO_ANSWER;
    }
    // "On this device" is a promise about privacy, so it is only said when the SDK says it.
    const source = result.response.inferenceSource === ON_DEVICE ? ON_DEVICE : IN_CLOUD;
    return { text, source };
  } catch {
    return NO_ANSWER; // neither model could be asked
  }
}

/**
 * Call from a press (Start, Play): Chrome only starts downloading its on-device model
 * after one. When the model is already there, hold one idle session for the length of
 * the call, so the first alert does not wait for the model to load.
 * @returns {Promise<void>}
 */
export async function warmExplainer() {
  warmRun += 1;
  const run = warmRun;
  await loading;
  if (ready === null) {
    return;
  }
  try {
    await ready.model.initializeDeviceModel();
    const promptApi = globalThis.LanguageModel;
    if (warm !== null || promptApi === undefined) {
      return;
    }
    if ((await promptApi.availability(ready.deviceOptions)) !== "available") {
      return;
    }
    const session = await promptApi.create(ready.deviceOptions);
    if (run !== warmRun) {
      session.destroy(); // the call ended, or another began, while the model was loading
      return;
    }
    warm = session;
  } catch {
    // No on-device model in this browser: cloud Gemini answers instead.
  }
}

/** The call is over: let go of the idle session, so Chrome can unload the model. It
 *  never throws: the code that ends a call still has an alert sheet to close. */
export function restExplainer() {
  warmRun += 1;
  const session = warm;
  warm = null;
  if (session === null) {
    return;
  }
  try {
    session.destroy();
  } catch {
    // Already gone. There is nothing left to let go of.
  }
}
