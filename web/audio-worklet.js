/*
 * Second Ear — mic capture worklet.
 *
 * Runs on the audio thread inside the browser. Its only job: take the mic's
 * native-rate float samples, mix to mono, resample to 16 kHz, convert to signed
 * 16-bit little-endian, and post 250 ms frames (8 000 bytes) to the main thread.
 *
 * Contract (docs/SPEC.md §2): 16 000 Hz, mono, s16le, 250 ms per message. Raw PCM,
 * never MediaRecorder — only the first webm chunk carries a header and the rest
 * fail to decode on the server.
 *
 * Scaffold only: the processor is not registered yet. Phase 3 writes it and
 * app.js loads this file with audioWorklet.addModule("audio-worklet.js").
 */

// TODO(phase 3): class SecondEarCapture extends AudioWorkletProcessor
//   - buffer frames until 4 000 samples (250 ms at 16 kHz)
//   - postMessage(frame.buffer, [frame.buffer]) — transfer, never copy
//   - downsample by averaging input blocks; handle 44.1 kHz and 48 kHz inputs
// registerProcessor("second-ear-capture", SecondEarCapture);
