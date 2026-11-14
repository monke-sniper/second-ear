/*
 * Second Ear — capture worklet. Runs on the browser's audio thread.
 * In: whatever is connected to it (the mic, or a recording in demo mode) at the
 * context's own rate. Out: 250 ms frames of 16 kHz mono s16le, 8 000 bytes each.
 * It does not open the socket, keep audio, or know what is being said.
 *
 * Contract (docs/SPEC.md §2). Raw PCM, never MediaRecorder: only the first webm
 * chunk carries a header and the rest fail to decode on the server.
 */

const TARGET_RATE = 16000;
const FRAME_SAMPLES = 4000; // 250 ms at 16 kHz
const BYTES_PER_SAMPLE = 2;
const QUANTUM = 128; // samples per process() call when nothing is connected
const INT16_MAX = 32767;
const LITTLE_ENDIAN = true;

class SecondEarCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new DataView(new ArrayBuffer(FRAME_SAMPLES * BYTES_PER_SAMPLE));
    this.filled = 0; // samples written to the current frame
    this.sum = 0; // input samples waiting to be averaged into one output sample
    this.count = 0;
    this.phase = 0; // grows by TARGET_RATE per input sample; an output is due at sampleRate
  }

  /**
   * Mix to mono, then resample by averaging. At 48 kHz every output sample is the
   * mean of 3 inputs; at 44.1 kHz of 2 or 3 in turn, which lands on exactly 16 000
   * per second. With nothing connected the input is silence, so the clock still moves.
   */
  process(inputs) {
    const channels = inputs[0] || [];
    const length = channels.length > 0 ? channels[0].length : QUANTUM;
    for (let index = 0; index < length; index += 1) {
      let mono = 0;
      for (let channel = 0; channel < channels.length; channel += 1) {
        mono += channels[channel][index];
      }
      this.sum += channels.length > 1 ? mono / channels.length : mono;
      this.count += 1;
      this.phase += TARGET_RATE;
      if (this.phase >= sampleRate) {
        const value = this.sum / this.count;
        // `while`, not `if`: a context slower than 16 kHz repeats the sample.
        while (this.phase >= sampleRate) {
          this.phase -= sampleRate;
          this.write(value);
        }
        this.sum = 0;
        this.count = 0;
      }
    }
    return true;
  }

  /** Float -1..1 in, one s16le sample out. A full frame is transferred, never copied. */
  write(value) {
    const clipped = Math.max(-1, Math.min(1, value));
    this.frame.setInt16(
      this.filled * BYTES_PER_SAMPLE,
      Math.round(clipped * INT16_MAX),
      LITTLE_ENDIAN,
    );
    this.filled += 1;
    if (this.filled < FRAME_SAMPLES) {
      return;
    }
    const buffer = this.frame.buffer;
    this.port.postMessage(buffer, [buffer]);
    this.frame = new DataView(new ArrayBuffer(FRAME_SAMPLES * BYTES_PER_SAMPLE));
    this.filled = 0;
  }
}

registerProcessor("second-ear-capture", SecondEarCapture);
