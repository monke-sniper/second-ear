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

## Rules

- 16 kHz mono wav is easiest; `soundfile` reads anything libsndfile handles.
- Everyone audible agreed to be recorded. State it in the README, not here.
- `demo_scam.wav` is the recording the demo console replays. It stays local; it is not part
  of the submission repo and not part of the README.
- Score the 20 improvised calls once, after detection freezes. Re-scoring after tuning is
  exactly the thing the honesty criterion punishes.
