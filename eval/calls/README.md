# eval/calls

Recordings and their labels. Audio is gitignored on purpose — these are people's voices.

## Naming

`01_grandparent.wav`, `02_pharmacy.wav`, … Use the same stem in `labels.csv`.

## labels.csv

```
file,label,scam_type,money_ask_s
01_grandparent.wav,1,grandparent,38
02_pharmacy.wav,0,,
```

- `label` — 1 scam, 0 legitimate.
- `scam_type` — one of the explainer's types, blank for legitimate calls.
- `money_ask_s` — the second the caller asks for money or a code, blank if there is none.
  This is what makes "alerted before the ask" computable.

## Recording a call

ffmpeg does it with nothing new to install. Put the phone on speaker next to the laptop,
then, from the repo root:

    ffmpeg -f dshow -i audio="Microphone (2- Realtek(R) Audio)" -ac 1 -ar 16000 -c:a pcm_s16le eval\calls\01_grandparent.wav

Press `q` to stop. `ffmpeg -list_devices true -f dshow -i dummy` lists the microphone names
if that one is not yours. A file recorded some other way (a phone, Voice Recorder) converts
with:

    ffmpeg -i in.m4a -ac 1 -ar 16000 -c:a pcm_s16le eval\calls\01_grandparent.wav

Then add its row to `labels.csv`, and note the second of the money ask while it is fresh.

## Rules

- 16 kHz mono 16-bit wav only. `eval/run_eval.py` refuses anything else and prints the
  ffmpeg line that converts it; it never resamples quietly.
- Everyone audible agreed to be recorded. State it in the README, not here.
- `demo_scam.wav` is the recording the demo console replays. It stays local; it is not part
  of the submission repo and not part of the README.
- Score the 20 improvised calls once, after detection freezes. Re-scoring after tuning is
  exactly the thing the honesty criterion punishes.
