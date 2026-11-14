# SPEC — the frozen contract

Everything in this file is fixed for the weekend. Changing a number or a message shape means
editing this file **and** the spec test that pins it, in the same commit. Where this file and
Part 1 of the weekend plan disagree, the plan wins and this file is wrong — say so, don't
quietly follow either.

## 1. What the system is

Phone A plays the call on speaker. A laptop nearby has this app open; its mic hears the call.

1. Capture mic audio as 250 ms frames, 16 kHz mono s16le PCM.
2. Cut 2–6 s chunks at pauses.
3. Transcribe each chunk to English (faster-whisper, `base.en`, CUDA).
4. Score the running transcript 0..1 (DistilBERT, last 256 tokens, left-truncated).
5. Turn scores into an alert level: `none` / `caution` / `scam`.
6. Count spoken digits in a 10 s window and raise a code warning when gated on.
7. On a new alert, ask Haiku (4 s budget) for the scam name, the line to say, and the claimed
   organisation's official number.
8. Send at most one ntfy push per alert type per call.
9. Render it on a 360 px-wide screen, designed for someone who cannot easily read small print.

Non-goals: joining or recording the call, blocking numbers, deciding anything for the user.
The audio is never written to disk by the app.

## 2. Frozen numbers

| Rule | Value |
|---|---|
| Audio | 16 000 Hz, mono, signed 16-bit little-endian |
| Client frame | 250 ms = 8 000 bytes (16 000 × 2 × 0.25) |
| Chunk | cut at a pause; min 2.0 s, max 6.0 s |
| Caution | smoothed risk ≥ 0.50 |
| Smoothing window | mean of the last 3 chunk scores |
| Scam | two consecutive raw scores > 0.85 |
| Scam stickiness | once scam, scam for the rest of the call |
| Digit warning | ≥ 6 digits counted within the last 10.0 s |
| Digit counting | spoken or written; only numbers of 2+ digits count; `oh` is 0 only next to another number word |
| Digit gate | fires only while risk > 0.50 or a scam alert is active |
| Explainer context | last 60 s of transcript, every number of 2+ digits replaced with `[number]` |
| Explainer timeout | 4.0 s, total |
| Push | max one scam and one code attempt per call, success or not; never contains digits |
| Scorer window | last 256 tokens, left truncation |

Comparisons are strict where written strict (`> 0.85`) and inclusive where written `≥`.

## 3. Wire protocol

Client → server:

- **binary frame**: raw PCM as above. 8 000 bytes is one frame; the server accepts anything
  up to 64 KiB and re-frames.
- **text `{"type": "reset"}`**: start a new call. Clears transcript, score history, alert
  state, and push flags. Resets `t_s` to 0. (Phase 3)

Server → client, one JSON object per event. Canonical shapes live in `server/contracts.py`.

| type | fields |
|---|---|
| `ack` | `bytes`, `total` |
| `transcript` | `text`, `t_s` |
| `risk` | `score`, `t_s`, `level` |
| `danger` | `digit_count`, `t_s` |
| `alert` | `level`, `t_s`, `trigger`, `score` |
| `explainer` | `t_s`, `scam_type`, `reason`, `safe_exit_line`, `org`, `org_name`, `official_number`, `degraded` |
| `error` | `detail` |

`t_s` is seconds since the call started. Nothing on the wire ever carries a raw digit run.

`alert` is emitted by the rules and must not wait for the explainer — the sheet has to be on
screen while the scammer is still talking. `explainer` follows within its 4 s budget and
enriches the open alert; a missing or degraded `explainer` changes nothing about the level.

HTTP:

- `GET /health` → `{"status": "ok"}`
- `POST /simulate` → `{"chunks": ["..."], "chunk_seconds": 4.0}` in,
  `{"timeline": [{"t_s", "score", "level"}], "alerts": [...], "explainers": [...], "danger": [...]}`
  out. Returns **501** until Phase 3 implements the pipeline.
- `GET /` → `web/index.html`; the rest of `web/` is served statically.

## 4. Module contracts

Bodies land in Phases 3–4. Signatures are already listed in the code and are not to be
reshaped without updating `contracts.py` and the spec tests.

- **`chunker.AudioChunker.feed(pcm) -> list[bytes]`** — append frames to an internal buffer,
  return every chunk that is ready. A chunk closes at a detected pause once it is ≥ 2 s, and
  is force-closed at 6 s. `flush()` returns the tail, `reset()` clears.
- **`stt.StreamTranscriber.transcribe(pcm) -> TranscriptChunk`** — one chunk in, English text
  out. `task="translate"` so non-English audio still lands in English. `vad_filter=True` so
  silence never becomes invented words. Target: ≤ 1 s behind the call on the 4060.
- **`scorer.RiskScorer.score(transcript) -> float`** — 0..1, monotone-ish, tolerant of empty
  input (empty → 0.0). `DistilBertRiskScorer` reads the last 256 tokens. `StubScorer` returns
  0.0 so the app runs before the model exists.
- **`alerts.decide(history) -> AlertDecision`** — pure function over the full score history,
  no hidden state. Recompute each chunk; O(n) on a call of tens of chunks is free.
  `trigger` is `two_high_chunks` for scam and `smoothed_risk` for caution. `t_s` and `score`
  are the time and the value that crossed the threshold: the raw score for scam, the smoothed
  score for caution. Caution is not sticky; it clears when the smoothed risk falls below 0.50.
- **`danger.scan(chunks, risk, scam_active, now_s) -> DangerDecision`** — joins the chunks in
  the window, finds every number (`four five six`, `oh four`, `double seven`, `sixteen`,
  numerals), counts the digits, applies the gate. A number is number words or numerals
  separated only by spaces, commas, dots, dashes or filler sounds (`uh`, `um`). Only numbers
  of 2+ digits count, so `this one` is not a digit, and `oh` is a zero only when it touches
  or sits between number words, so `oh, really` is not one either. The returned model has
  `fired`, `digit_count`, `window_s`, `at_s` and nothing else.
- **`explainer.Explainer.explain(transcript, risk) -> ExplainerResult`** — never raises,
  never changes the alert level, degrades to the generic line, and returns within the 4 s
  budget even when the request hangs (the request is abandoned, not awaited).
- **`notify.NtfyNotifier.send_scam(...)` / `send_code()`** — one attempt each per call.
  Returns `False` on a repeat, a failed POST or a disabled topic; a failed POST is not
  retried. Publishes JSON to the ntfy root URL, so the topic is never part of a URL.

## 5. Explainer rules

- Input: last 60 s of transcript, every number of 2+ digits replaced with `[number]`
  **before** the request, spoken (`four five six`) or written. Spaces, commas, dots, hyphens
  and filler sounds between digits do not break a number, so `4111 1111 1111 1111`,
  `4111, 1111, 1111, 1111` and `123 45 6789` are each one number, and a three-digit security
  code or a four-digit PIN is caught too. A lone digit (`this one`) stays, unless six or more
  lone digits are left in the context; then they are replaced as well. No digit run may
  appear anywhere in the prompt. (This follows Part 1 of the plan, "numbers removed"; the
  6+ rule this file had before was the weaker reading.)
- Output: JSON only — `{"scam_type", "reason", "safe_exit_line", "claimed_org"}`. A code
  fence around the object is tolerated.
- Validation, all must pass: parses as JSON; `safe_exit_line` 3–160 chars and contains no
  digits and no spoken number; `reason` ≤ 120 chars and no run of 6+ digits; `scam_type` is
  in the fixed list or `other`; `claimed_org` is an id in `server/orgs.json` or `null`.
- On timeout, bad JSON, or a failed validation: return the generic line,
  `degraded=true`, `org=null`, `official_number=null`, with `scam_type=other` and the reason
  `The call sounds like a scam.` The alert itself stays standing.
- `official_number` is filled only when the organisation has `phone`, `source_url` and
  `verified_at` set.
- Nothing from the call is logged: a degraded result logs a fixed reason code and at most an
  exception class name, never the transcript, the reply, or an exception message.
- Fixed scam types: `grandparent`, `medicare`, `ssn`, `refund`, `tech_support`, `gift_card`,
  `reward`, `romance`, `bank_fraud`, `other`.
- Generic safe-exit line: `I'll call you back at the number on my card.`
- One call per alert, never per chunk.

## 6. Data and training

Verified against the dataset on Nov 14:

- `BothBosu/scam-dialogue` on Hugging Face, Apache-2.0, synthetic, generated with
  `meta-llama-3-70b-instruct`.
- `scam-dialogue_train.csv` 1 280 rows, `scam-dialogue_test.csv` 320 rows.
- Columns: `dialogue`, `type`, `label`. Label 1 = scam (`ssn`, `refund`, `support`, `reward`),
  label 0 = legitimate (`delivery`, `insurance`, `telemarketing`, `wrong`).
- Speaker tags are **inline and lowercase**: `caller:` and `receiver:` — not `Suspect:` /
  `Innocent:` as the earlier draft assumed. Strip them; live transcripts have no labels.

Training rules:

- Split by conversation **before** augmenting; the given test split is the test split.
- Augment train and val only: prefixes at 20/40/60/80/100 % of each dialogue's words, same
  label.
- `distilbert-base-uncased`, `max_length=256`, `truncation_side="left"`, 3 epochs,
  `lr=2e-5`, fp16. Checkpoint to Drive every epoch.
- Report precision, recall and F1 on full test dialogues **and** on 40 % prefixes.
- Never train on the held-out Gemini set. Never tune on the 20 improvised calls; they are
  scored once, after the freeze.
- Baselines on the same split: keyword list, and Claude Haiku zero-shot.
- The matched-pairs generator (Claude, at kickoff) must hold topic constant between the scam
  and the real call and vary endings the same way in both.

## 7. Privacy

- Audio is not persisted by the app. The only audio files are the consented eval recordings.
- Transcripts live in memory. Nothing containing digits is logged.
- The ntfy topic is secret, lives in `.env`, never in the repo.
- Demo recordings need consent from everyone audible; the README says so.

## 8. Eval outputs

- `eval/results/model.json`, `eval/results/baselines.json`
- `eval/results/table.md` — columns: test, metric, value, n, notes. One row per metric, with
  its count. Results split by language and by failure mode.
- `eval/results/risk_scam.png`, `eval/results/risk_normal.png`
- `eval/results/failures.md` — at least three wrong calls, each with a snippet and the reason.

## 9. Decisions made in this scaffold

Don't re-litigate these mid-build; raise them instead.

- **torch is CPU, Whisper is GPU.** DistilBERT is 66M params and scores in ~30 ms; training
  is in Colab. One CUDA stack (CTranslate2) in the process, no 2.5 GB torch download.
- **`base.en`, not `small.en`.** Latency beats a few WER points for a live warning.
- **Smoothing window is 3.** The plan says "smoothed" without a number; 3 is the smallest
  window that kills a single noisy chunk without lagging a real escalation by much.
- **Alerts are pure functions over history.** No hidden state means `/simulate` and the live
  loop cannot drift apart.
- **`orgs.json` phones are `null`.** They must be checked on the official site; inventing a
  number is the one failure that could send someone to a scammer.
- **Static mount at `/` after the routes**, so `index.html` and its relative scripts work
  with no build step.
- **No CI.** A private 48-hour repo whose test job would download torch is slower than the
  bugs it catches. `pytest -q` before every commit instead.

Added in Phase 4:

- **Explainer request.** Thinking disabled, effort `low`, 256 output tokens, no retries, no
  JSON schema (a new schema pays a one-time compile on first use, the wrong risk under 4 s).
  The optional params live in `explainer.REQUEST_OPTIONS`; `scripts/smoke_explainer.py`
  says whether the API accepts them. If it refuses one, delete it.
- **Push.** One JSON POST, 3.0 s timeout, priority 4 (`high`). Fixed titles; the body is the
  scam label plus the reason with every digit removed, or a fixed sentence when the explainer
  degraded. The callback number and the line to say never go in a push.
- **Known limits of digit counting, all behind the risk gate.** `ten minutes` counts 2, a
  date like `14, 2026` counts 6, and digits read with whole words between them
  (`four, okay, one`) are not counted. Letters in a gift-card code are not digits.
- **`risk_softened`** is named in `contracts.py` but has no rule yet. Nothing emits it.

## 10. Open items

- Organisation phone numbers — every entry in `server/orgs.json` needs a verified number
  and a `verified_at` date.
- Kaggle API token for the cross-dataset test (Sunday only).
- A recorded demo call at `eval/calls/demo_scam.wav` and a matching row in `labels.csv`.
- The design system in `docs/design/` was authored at scaffold time, not sourced from a
  designer. Treat it as the spec anyway; changes go through this file.

## 11. Cut order when behind

Spanish → browser check → plots. Never cut the 20 recorded calls, the alert rules, or the
honest results table.
