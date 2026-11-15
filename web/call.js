/*
 * Second Ear — one call's audio path: a source, the capture worklet, the socket.
 * In: the mic, or a recording's bytes in demo mode. Both go through the same
 * worklet and the same /ws/audio. Out: every server event, handed to `onEvent`.
 * It draws nothing and decides nothing; it never keeps audio.
 */

const WS_URL = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/audio`;
const WORKLET_URL = "audio-worklet.js";
const PROCESSOR = "second-ear-capture";
const RESET_MESSAGE = JSON.stringify({ type: "reset" });
// One frame as the worklet sends it: 250 ms of 16 kHz mono s16le.
const FRAME_BYTES = 8000;
// Quiet sent before the socket closes: 1 s, so the server sees a pause and closes the
// last chunk itself instead of having the last words cut off where the socket ended.
const STOP_SILENCE_FRAMES = 4;
// The mic hears a speakerphone across the table: leave the far voice alone, lift it.
const MIC = {
  audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: true },
};

/** The call in progress, or null: { context, socket, tap, stream, source }. */
let live = null;
let sentBytes = 0;

/** Audio bytes sent on this call so far. The server's `ack.total` counts the same. */
export function bytesSent() {
  return sentBytes;
}

/** False on plain http away from localhost, where the browser hides the mic. */
export function micSupported() {
  return Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

function parse(data) {
  if (typeof data !== "string") {
    return null;
  }
  try {
    return JSON.parse(data);
  } catch {
    return null; // not ours; the server only sends JSON
  }
}

/** Open /ws/audio and start a new call on it. Resolves once `reset` has been sent. */
function openSocket(handlers) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(WS_URL);
    let opened = false;
    socket.binaryType = "arraybuffer";
    socket.onopen = () => {
      opened = true;
      socket.send(RESET_MESSAGE);
      resolve(socket);
    };
    socket.onmessage = (message) => {
      const event = parse(message.data);
      if (event !== null) {
        handlers.onEvent(event);
      }
    };
    socket.onclose = () => {
      if (opened) {
        handlers.onClose(); // only an unexpected close gets here; stopCall() unhooks first
      } else {
        reject(new Error("the audio socket did not open"));
      }
    };
  });
}

/** The shared half of a call: context, worklet, socket, frames flowing to the server. */
async function openCall(handlers) {
  stopCall();
  const context = new AudioContext();
  let socket = null;
  try {
    await context.audioWorklet.addModule(WORKLET_URL);
    if (context.state === "suspended") {
      await context.resume();
    }
    socket = await openSocket(handlers);
  } catch (error) {
    context.close().catch(() => {});
    throw error;
  }
  const tap = new AudioWorkletNode(context, PROCESSOR);
  sentBytes = 0;
  tap.port.onmessage = (message) => {
    if (socket.readyState === WebSocket.OPEN) {
      sentBytes += message.data.byteLength;
      socket.send(message.data);
    }
  };
  // A silent path to the output keeps the browser pulling audio through the worklet.
  const mute = context.createGain();
  mute.gain.value = 0;
  tap.connect(mute).connect(context.destination);
  live = { context, socket, tap, stream: null, source: null };
  return live;
}

/**
 * Ask for the mic, then stream it. Rejects if the mic is refused or the socket fails.
 * `handlers.onMicEnded` fires if the mic stops on its own mid-call: unplugged, or taken
 * away by the browser or the system. Stopping the call here does not fire it.
 */
export async function startMicCall(handlers) {
  const stream = await navigator.mediaDevices.getUserMedia(MIC);
  const tracks = stream.getAudioTracks();
  try {
    const call = await openCall(handlers);
    if (tracks.some((track) => track.readyState === "ended")) {
      // It stopped while the socket was opening, before anyone was listening for it.
      throw Object.assign(new Error("the microphone stopped"), { name: "MicEndedError" });
    }
    const source = call.context.createMediaStreamSource(stream);
    source.connect(call.tap); // to the worklet only: the mic is never played back
    tracks.forEach((track) => {
      track.onended = () => handlers.onMicEnded();
    });
    live = { ...call, stream, source };
  } catch (error) {
    stream.getTracks().forEach((track) => track.stop());
    stopCall(); // closes the socket and the context if they had already opened
    throw error;
  }
}

/**
 * Demo mode: play a recording out loud and stream the same samples. No mic.
 * `handlers.onEnded` fires when the recording has played through; the call stays
 * open so the caller can let the last chunk and the explainer arrive.
 * Returns the recording's length in seconds.
 */
export async function startRecordingCall(bytes, handlers) {
  const call = await openCall(handlers);
  try {
    // decodeAudioData empties the buffer it is given, so it gets a copy.
    const buffer = await call.context.decodeAudioData(bytes.slice(0));
    const source = call.context.createBufferSource();
    source.buffer = buffer;
    source.connect(call.tap);
    source.connect(call.context.destination);
    source.onended = () => handlers.onEnded();
    source.start();
    live = { ...call, source };
    return buffer.duration;
  } catch (error) {
    stopCall();
    throw error;
  }
}

/**
 * End the call: stop the tracks or the playback, send a second of quiet, close the
 * socket and the context. The quiet is queued before the close, so it still goes out.
 */
export function stopCall() {
  if (live === null) {
    return;
  }
  const { context, socket, stream, source } = live;
  live = null;
  if (source !== null) {
    source.onended = null;
    source.disconnect();
  }
  if (stream !== null) {
    stream.getTracks().forEach((track) => {
      track.onended = null;
      track.stop();
    });
  }
  socket.onclose = null;
  socket.onmessage = null;
  if (socket.readyState === WebSocket.OPEN) {
    for (let frame = 0; frame < STOP_SILENCE_FRAMES; frame += 1) {
      socket.send(new ArrayBuffer(FRAME_BYTES)); // a new buffer is all zeros: silence
      sentBytes += FRAME_BYTES;
    }
  }
  socket.close();
  context.close().catch(() => {});
}
