# SPEC — the frozen contract

Everything in this file is fixed for the weekend. Changing a number or a message shape means
editing this file **and** the spec test that pins it, in the same commit. Where this file and
Part 1 of the weekend plan disagree, the plan wins and this file is wrong — say so, don't
quietly follow either.

## 1. What the system is

Phone A plays the call on speaker. A laptop nearby has this app open; its mic hears the call.

1. Capture mic audio as 250 ms frames, 16 kHz mono s16le PCM.
2. Cut 2–6 s chunks at pauses.
3. Transcribe each chunk to English (faster-whisper, `base.en`, CUDA; cpu/int8 if CUDA fails).
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
| End-of-call tail | audio after the last chunk is heard if it is ≥ 0.5 s and not silent |
| Caution | smoothed risk ≥ 0.50 |
| Smoothing window | mean of the last 3 chunk scores |
| Scam | two consecutive raw scores > 0.85 |
| Scam stickiness | once scam, scam for the rest of the call |
| Digit warning | ≥ 6 digits counted within the last 10.0 s |
| Digit counting | spoken or written; only numbers of 2+ digits count; `oh` is 0 only next to another number word |
| Digit gate | fires only while the latest raw chunk score > 0.50 or a scam alert is active |
| Explainer context | last 60 s of transcript, every written digit and every number word replaced with `[number]` |
| Explainer timeout | 4.0 s, total |
| Push | max one scam and one code attempt per call, success or not; never contains digits |
| Scorer window | last 256 tokens, left truncation |

Comparisons are strict where written strict (`> 0.85`) and inclusive where written `≥`.

## 3. Wire protocol

Client → server:

- **handshake**: `/ws/audio` is for the app's own page. A request whose `Origin` header
  names a host other than `localhost` or `127.0.0.1` is refused before the socket opens
  (HTTP 403). A request with no `Origin` is accepted: a browser always sends one, so only
  a script or a test comes without.
- **binary frame**: raw PCM as above. 8 000 bytes is one frame; the server accepts anything
  up to 64 KiB and re-frames. A larger message gets an `error` and is not counted.
- **text `{"type": "reset"}`**: start a new call. Clears transcript, score history, alert
  state, and push flags. Resets `t_s` and the ack `total` to 0. It sends no reply. An
  explainer answer still on its way for the old call is dropped, with the scam push that
  would have followed it.
- **any other text**: an `error` naming the message's `type` (`unknown` if it is not a
  plain lowercase name). The client's text is never copied into the reply.

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
An answer for an alert that a higher alert has since replaced is not sent: a slow `caution`
answer never arrives after the `scam` alert, so it cannot overwrite the scam answer.

What is sent, and when:

- `transcript` and `risk` follow every chunk that has words. `risk.score` is that chunk's
  raw score. `risk.level` is what the rules say now, so it can fall back from `caution`.
- `alert` is sent only when the level rises above the highest one already sent in this call
  (`none` → `caution` → `scam`). There is no "back to none" event: `alerts.decide` lets
  caution clear, but the screen keeps the sheet open until the person closes it.
- `danger` is sent at most once per call.
- A chunk with no speech, or one that comes back with no text, adds no score point and
  sends nothing. It only moves the clock.
- A chunk Whisper fails on is treated as silence too, but the client is told: one `error`
  with the detail `could not process that audio`, at most once per call. The client shows
  it in the status line, so a call that is not being read does not look like a quiet one.
- `transcript.text` has every written digit replaced with `[number]`, in a run of any
  length, and every spoken number of 2+ digits as well. A lone spoken digit is ordinary
  speech and stays (`no one called`). The raw text stays in memory, for the scorer and the
  digit count only.
- Hanging up is not a reset: an explainer answer and a scam push already on their way are
  allowed to finish. The audio no chunk had closed over is heard as well, if it is at least
  0.5 s long and not silent. It goes through the same rules as any chunk, so the last words
  of a call can still raise an alert or the code warning, and their pushes go out. Nothing
  is sent to the closed socket.

HTTP:

- `GET /health` → `{"status": "ok"}`
- `POST /simulate` → `{"chunks": ["..."], "chunk_seconds": 4.0}` in,
  `{"timeline": [{"t_s", "score", "level"}], "alerts": [...], "explainers": [...], "danger": [...]}`
  out. Runs the same session and rules as the socket, with the explainer once per alert.
  It never sends a push. An empty chunk adds no timeline point.
- `GET /demo/audio` → the recording demo mode replays: `eval/calls/demo_scam.wav`, or
  `eval/calls/tts_scam.wav` if that is missing, as `audio/wav` with the file name in
  `Content-Disposition`. `404` when neither exists. No other file in that folder is served.
- `GET /` → `web/index.html`; the rest of `web/` is served statically.

## 4. Module contracts

Signatures are listed in the code and are not to be reshaped without updating
`contracts.py` and the spec tests.

- **`chunker.AudioChunker.feed(pcm) -> list[bytes]`** — append bytes to an internal buffer,
  return every chunk that is ready. A chunk closes at a detected pause once it is ≥ 2 s, and
  is force-closed at 6 s. A pause is `pause_frames` consecutive 250 ms frames quieter than
  `pause_db` (both in `ChunkerConfig`). Input of any size is re-framed. `flush()` returns a
  tail of ≥ `min_s` (2 s) or nothing, `reset()` clears. At the end of a call the socket
  lowers `min_s` on its own chunker to 0.5 s before it flushes (§3). `is_silent(pcm)` is
  true when every frame is that quiet; the app does not run Whisper on such a chunk.
- **`stt.StreamTranscriber.transcribe(pcm) -> TranscriptChunk`** — one chunk in, English text
  out. An `.en` model cannot translate, so it gets `language="en", task="transcribe"`; any
  other model gets `task="translate"` so non-English audio still lands in English.
  `vad_filter=True` so silence never becomes invented words, and
  `condition_on_previous_text=False` so each chunk is decoded on its own.
  `temperature=0.0` so a chunk is decoded once, with none of Whisper's retries at higher
  temperatures (§10 has the timing that decided it). **Hallucination guard:** a decoded
  segment is dropped when faster-whisper's own fields mark it as a failed decode:
  `compression_ratio > 2.4` (a repetition loop, reason code `compression_ratio`), or
  `no_speech_prob > 0.6` and `avg_logprob < -1.0` (words over silence, reason code
  `no_speech`). These are Whisper's reference thresholds and are not tuned. Whisper uses
  the first one to ask for a retry at a higher temperature; with one pass per chunk there
  is no retry, so the segment is removed instead, and a chunk that was only a
  hallucination comes back as empty text, which the session treats as silence. A drop is
  logged by its reason code and nothing else. The guard was added after the detection
  freeze (tag `detection-freeze`), from a near-silent call in manual testing; every
  number in `eval/results/` is from the frozen version. If CUDA fails, at
  load or on a decode, the model is reloaded on cpu/int8 and stays there. `warmup()`
  decodes once with the VAD off, so that failure shows at startup and not on the first
  word of a call. Target: ≤ 1 s behind the call on the 4060.
- **`scorer.RiskScorer.score(transcript) -> float`** — 0..1, monotone-ish, tolerant of empty
  input (empty → 0.0). `DistilBertRiskScorer` cleans the text the way training did
  (`ml/README.md`), in this order: whitespace collapsed with `" ".join(text.split())`; then
  `strip_greeting` once, on the start of the whole transcript, which removes one leading
  `hello`, `hi`, `hey` or `good morning` / `afternoon` / `evening` and the punctuation after
  it; then the last 256 tokens, left-truncated. A greeting later in the call is never
  touched, and a call that is so far only a greeting scores 0.0. `GREETING_PATTERN` and
  `strip_greeting` live in `server/greeting.py`, copied verbatim from training; a test pins
  the pattern. The keyword stand-in does not strip anything. `load_app_scorer()`
  returns it once `models/risk-scorer/` exists and `KeywordStandInScorer` until then:
  hand-set red-flag phrases over the last 200 words, there so the alerts can be seen
  working, with no accuracy claim. `load_scorer()` still returns `StubScorer` (always 0.0)
  when there is no model.
- **`pipeline.CallSession.ingest(text, duration_s) -> Step`** — one transcribed chunk in,
  its `transcript`, `risk`, `alert` and `danger` events out, in send order. It holds the
  call's clock, transcript and score history, and remembers the highest alert level already
  sent and whether the danger event went out. `reset()` starts a new call. The socket
  (`live.LiveCall`) and `/simulate` (`pipeline.simulate`) both run it, so they cannot drift.
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
  or sits between number words, so `oh, really` is not one either. `risk` is the latest
  raw chunk score, not the smoothed one. The returned model has `fired`, `digit_count`,
  `window_s`, `at_s` and nothing else.
- **`explainer.Explainer.explain(transcript, risk) -> ExplainerResult`** — never raises,
  never changes the alert level, degrades to the generic line, and returns within the 4 s
  budget even when the request hangs (the request is abandoned, not awaited).
- **`notify.NtfyNotifier.send_scam(...)` / `send_code()`** — one attempt each per call.
  Returns `False` on a repeat, a failed POST or a disabled topic; a failed POST is not
  retried. Publishes JSON to the ntfy root URL, so the topic is never part of a URL.

## 5. Explainer rules

- Input: last 60 s of transcript, every number replaced with `[number]` **before** the
  request: every written digit and every number word (`four five six`), a single one
  included (`this one`, `4`). Length is not the test, because a PIN read out slowly
  (`4, then 9, then 1, then 7`) is single digits with ordinary words between them. Spaces,
  commas, dots, hyphens and filler sounds between digits do not break a number, so
  `4111 1111 1111 1111`, `4111, 1111, 1111, 1111` and `123 45 6789` each become one
  `[number]`. An `oh` in the same run as a number goes with it, even across a comma or a
  full stop (`One. Oh.`), and so do the plurals `zeros` to `nines` (`two sevens`) and
  `nought`. No digit from the call may appear in the request; the only digits in it are
  the length limits in the fixed instructions. This is stricter than the screen and the
  push (§3), which keep a lone spoken digit because a person reads them. (Changed on
  Nov 15 after review. The rule before kept lone digits unless six or more were left,
  which let a four-digit PIN read slowly through.)
- What the input rule does not replace, none of it a digit of a code: words of size
  (`hundred`, `thousand`); ordinals (`fourth`, `twenty-first` becomes `[number]-first`);
  number words run together (`twentyone`); the letter `o` said for zero; and an `oh` with
  ordinary words on both sides (`four, then oh, then nine` keeps its `oh`), which cannot
  be told from the exclamation.
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
- **Provider.** `EXPLAINER_PROVIDER` in `.env` is `anthropic` (Haiku, the default) or
  `gemini`; anything else counts as `anthropic`. Gemini uses `GEMINI_API_KEY` and
  `GEMINI_MODEL`, the same settings `eval/make_heldout.py` uses, and is called over httpx
  with no extra dependency (`server/gemini_client.py`): `generateContent`, JSON output
  asked for, the key in the `x-goog-api-key` header and never in a URL. The provider
  picks the client, the model id and the optional request params (Anthropic's `thinking`
  and `output_config` are not sent to Gemini; Gemini gets minimal thinking). Every other
  rule in this section is the same for both: redaction before the request, the 4 s
  budget, validation, and the degraded result.
- No retries inside the 4 s budget, on either provider. A 503, a 429 or a timeout from
  Gemini degrades at once; the log line holds the HTTP status (`request_failed:http_503`)
  or an exception class name, and the error body is never read.
- The provider never touches detection. The scorer, the alert rules and the digit warning
  do not know which model the explainer asks.

## 6. Data and training

Verified against the dataset on Nov 14, at hub revision
`321b961b5ae353e19ed479b960658dcd223d5e06`. Both notebooks pin that revision.

- `BothBosu/scam-dialogue` on Hugging Face, Apache-2.0, synthetic, generated with
  `meta-llama-3-70b-instruct`.
- `scam-dialogue_train.csv` 1 280 rows, `scam-dialogue_test.csv` 320 rows.
- Columns: `dialogue`, `type`, `label`. Label 1 = scam (`ssn`, `refund`, `support`, `reward`),
  label 0 = legitimate (`delivery`, `insurance`, `telemarketing`, `wrong`).
- Speaker tags are **inline and lowercase**: `caller:` and `receiver:` — not `Suspect:` /
  `Innocent:` as the earlier draft assumed. Strip them; live transcripts have no labels.
- One training dialogue is a word-for-word copy of a test dialogue, and one training dialogue
  appears twice.
- Every dialogue, all 1 280 and all 320, opens with a greeting.

Training rules. This is recipe v3, `RUN_NAME` `distilbert-prefix-v3-opencrop`. **v3 is the
final model whatever it scores, and nothing is chosen using the test split.**

- Training data is BothBosu only. There is no matched-pairs set.
- Clean every row the same way, in train, val and test, before the split: strip the speaker
  tags, collapse whitespace, then remove one leading greeting with `strip_greeting` (`hello`,
  `hi`, `hey`, `good morning` / `afternoon` / `evening`, and the punctuation after it). One
  rule for every row and both labels. The rule lives in the notebooks' shared helpers cell
  and, copied verbatim, in `server/greeting.py`; `tests/test_scorer.py` pins the pattern. A
  rule change changes all three together (§4).
- Drop the two leaking training rows (the copy of a test dialogue and the duplicate). Then
  split train into train and val by conversation, 90/10, stratified by `type`, seed 42:
  1 150 train and 128 val conversations. The given test split is the test split, untouched
  at 320. All of this happens **before** augmenting.
- Augment train and val only, in two steps. First, prefixes at 20/40/60/80/100 % of each
  dialogue's words, same label. Then, for every prefix example, one copy with its first k
  words removed, k uniform 5 to 15, seeded, same label; an example of k words or fewer gets
  no copy. That gives 5 750 + 5 728 = 11 478 training examples and 640 + 639 = 1 279 val
  examples. The test split is never augmented.
- `distilbert-base-uncased`, `max_length=256`, `truncation_side="left"`, 3 epochs,
  `lr=2e-5`, fp16. Checkpoint to Drive every epoch.
- The model is the end of epoch 3. Val is watched; it never picks a checkpoint or a
  threshold.
- Report precision, recall and F1 at P(scam) ≥ 0.5 on full test dialogues **and** on 40 %
  prefixes. The headline tests, `bothbosu_test_full` and `bothbosu_test_prefix40`, use the
  greeting-free text. A second pair, `…_with_greeting`, scores the original text, so the
  before and after sit side by side.
- Never train on the held-out Gemini set. Never tune on the 20 improvised calls; they are
  scored once, after the freeze.
- Baseline on the same four tests: the keyword list in `ml/README.md`, any hit means scam,
  matched case-insensitively as whole phrases with plurals allowed. The list and the
  matching rule are fixed; never tune them on the test split. A Claude Haiku zero-shot
  baseline is not built.

Two of these depart from Part 1 of the plan, by the owner's decision on Nov 14, because the
build is solo: there is no matched-pairs set and no Haiku zero-shot baseline.

Known limits of this test split. The training notebook recounts each one and writes it to
`model.json`.

- The dialogues are templated: 298 of the 320 test dialogues share their first 12 words with
  a training conversation.
- The opening gives the label away. With the greeting left in, looking up a test dialogue's
  first 6 words among the training conversations and taking their majority label is right
  for 295 of 320, with no model at all; in the train CSV, 639 of 640 scam dialogues open
  with `hello` and 384 of the 385 that open with `hi` are legitimate. With the greeting
  removed it is still 289 of 320, because the next sentence is templated too. That is why
  the opening-crop copies exist.
- 3 of the 320 40 % test prefixes are word for word identical to a training example.
- So scores on this split flatter the model. `model.json` carries two diagnostics outside
  its table rows: the headline tests with the first 12 words removed, and P(scam) for six
  hand-written lines, each bare, behind `hello` and behind `hi`.

## 7. Privacy

- Audio is not persisted by the app. The only audio files are the consented eval recordings.
- Transcripts live in memory. Nothing containing digits is logged.
- The ntfy topic is secret, lives in `.env`, never in the repo.
- Demo recordings need consent from everyone audible; the README says so.

## 8. Eval outputs

- `eval/results/model.json`, `eval/results/baselines.json` — one shape,
  `second-ear/results-v1`, described in `ml/README.md`. Their `rows` are already in the
  table's columns. A metric with a zero denominator is `null`, never 0. Neither file holds
  dialogue text.
- `eval/heldout/gemini.jsonl` — the held-out set: 100 short calls written by Gemini, 50 scam
  and 50 legitimate, no speaker labels. The four openings (`hello`, `hi`, none, `this is`)
  are dealt to both labels by one rule, in code. `eval/heldout_brief.py` holds the brief,
  committed before the first request; `eval/make_heldout.py` checks format only, runs no
  scorer and writes the set once. `gemini.meta.json` records the model and the brief's
  hash. Never trained on, never tuned on.
- `eval/results/heldout.json` — the same shape with two systems, so each row also carries
  `system`: the app scorer (`load_app_scorer()`, scam at score ≥ 0.5) and the keyword
  baseline, on the full text (`gemini_heldout_full`) and on the first 40 % of its words
  (`gemini_heldout_prefix40`).
- `eval/results/calls.json` — the recorded calls, from `python -m eval.run_eval`. Every wav
  listed in `eval/calls/labels.csv` (16 kHz mono 16-bit; anything else is refused) goes
  through the real chunker, Whisper and `CallSession`, offline, with no explainer and no
  push. At the end of a recording the audio no chunk had closed over is heard when it is at
  least 0.5 s and not silent, as the live socket does. Per call: label, first alert level
  and time, scam alert time, alerted before `money_ask_s`, digit warning fired, and the
  risk timeline. No transcript text. Totals under test `recorded_calls`, each with its n:
  `catch_rate`, `false_alarm_rate`, both again at scam level,
  `median_seconds_to_first_alert`, `alerted_before_money_ask`, `danger_fired_rate`.
  **Caught means any alert, caution or scam; a false alarm is any alert on a legitimate
  call.** That was fixed before any recorded call was scored. Alert times are audio time at
  the end of the chunk that raised the alert; a live call adds the decode time. The run
  refuses to score the calls a second time, and `--dry-run` writes nothing.
- Every results file made by `eval/` has a `scorer` block: its name, the sha256 of
  `model.json` when that file exists, and for the trained model the sha256 of its weights
  and whether `model.json` describes them. When the scorer is the keyword stand-in, the
  file's `caveats` say so.
- `eval/results/table.md` — columns: test, metric, value, n, notes. One row per metric, with
  its count: `n` is that metric's own denominator (dialogues flagged as scam for precision,
  scam dialogues for recall, every dialogue scored for F1), and the notes give the total.
  One section per results file and system, every number copied from its file;
  `python -m eval.run_eval --table-only` rebuilds it. Results split by language and by
  failure mode.
- `eval/results/risk_scam.png`, `eval/results/risk_normal.png` — not built. `calls.json`
  keeps each call's risk timeline, so they can be drawn without running Whisper again.
- `eval/results/failures.md` — every missed scam and every false alarm, each with the facts
  from the run and a snippet with its numbers replaced. Calls alerted after the money ask
  are listed as late, not as wrong. The reason in words is added by a person after
  listening.

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

Added after the Nov 14 review:

- **The end of a call is heard.** When the socket closes, `live.LiveCall` flushes its
  chunker with the floor lowered to 0.5 s and runs the tail as its own task. Once the
  client has gone, the explainer is asked only for a scam alert, because only that answer
  is used (in the push). Stop in the browser sends 1 s of silence (four frames) before it
  closes the socket, so the server usually sees a pause and closes the last chunk the
  ordinary way.
- **Known limits of the end of a call.** The browser's last 0.25–0.5 s before Stop never
  reaches the server: a part-filled worklet frame is not sent, and frames still queued in
  the page are dropped once the socket is closing. A handler that is cancelled while a
  chunk is in Whisper (server shutdown, or the test client) loses that chunk's alert;
  uvicorn does not cancel a handler when the client hangs up.
- **One copy of the 2+ digits rule.** `explainer_prompt.NUMBER_MIN_DIGITS` is the only
  definition; the reply check, the wire, the pushes and the danger counter import it.
  `explainer_prompt.redact_outbound` is the one function a `transcript` event and a push
  body both go through. Since Nov 15 the prompt has its own, stricter rule (§5).
- **`NtfyNotifier.reset()` is not called by the app.** A new call gets a new notifier
  (Phase 3, below). The method stays for its spec test.

Added after the Nov 15 review:

- **The prompt's transcript holds no number.** `explainer_prompt.redact_for_prompt`
  replaces every number of one digit or more (§5), so `five thousand dollars` reaches the
  model as `[number] thousand dollars`. §5 lists what it leaves. The digit counter is not
  changed: `numbers.find_number_runs` takes `trim_loose_oh=False` for the prompt only, and
  the plurals are a pattern in `explainer_prompt`, so detection counts what it counted
  before.
- **Only the app's own page may open the audio socket.** The allowed `Origin` hosts are
  `localhost` and `127.0.0.1`, fixed in `app.LOCAL_HOSTS`. Serving the page from any other
  name (a LAN address, a tunnel) needs that set changed; it is not a setting.
- **Preflight: no CUDA device is a WARN.** Whisper on cpu/int8 is the normal path, so a
  laptop without CUDA passes. What still blocks: a foreign `site-packages`, the wrong
  Python, torch or CTranslate2 failing to import, and a failed Whisper decode.
- **A live call that ends closes the alert sheet.** Stop, a dropped connection and a
  stopped mic all go through one function in `app.js`. It closes the sheet and makes the
  page behind it usable again, so `Start listening` works after a connection drops under
  an open alert. The line to say goes with the sheet. The demo console is not changed: a
  replay that loses its connection keeps its sheet, and `Replay` is behind it until
  `This is a real call` is pressed.
- **A mic that stops ends the call.** When the mic's track ends on its own (unplugged, or
  taken by the system), the client stops the call and the status line says
  `The microphone stopped.` That line is new copy.
- **The DangerBanner's words are written when it shows**, not when the page loads, and
  emptied on reset. A screen reader announces a live region when its text changes.
- **The promise is `label` size.** `Second Ear never saves your calls.` was `caption`
  size (15 px), under the 18 px floor in `tokens.json`.

Added in Phase 5:

- **The client is five small modules, no build step.** `app.js` holds the one copy
  dictionary, routes server events and binds the buttons; `view.js` draws the components;
  `call.js` owns the audio graph and the socket; `demo.js` is the demo console;
  `audio-worklet.js` resamples to 16 kHz s16le and transfers 8 000-byte frames.
- **Demo mode is the live path with a different source.** The recording is decoded in the
  browser, played out loud, and fed to the same worklet and the same socket. The mic is
  never asked for. Because it is the live path, a replay sends the same pushes a live call
  would. When the recording ends the console sends 6.5 s of silence, then keeps the socket
  open until the server has acked all of it (60 s at most) and the explainer has had its
  4 s, so a slow Whisper cannot cut off the last alert.
- **Text replay.** With no recording on disk, the console posts a scripted grandparent call
  to `/simulate` and replays the answer through the same event handler at twice the call's
  pace, labelled `Text replay, no audio`. The code read-out is shown as `[number]`.
- **"This is a real call" is a screen state.** The server is not told. The sheet stays
  closed and the meter stays neutral for the rest of the call; the code warning and the
  pushes are not affected.
- **The DangerBanner shows no count.** It is the two fixed lines in
  `docs/design/components/danger-banner.md`. A third line, `{n} digits heard.`, was tried
  on Nov 14 and removed the same day, because the count can be wrong (§10).
  `danger.digit_count` stays on the wire for eval; the screen never shows it.
- **Two things in the design are not built.** The `Checked on …` source line of the
  OfficialNumberCard: the wire has no `source_url`, and adding one is a wire-shape change.
  The money-ask marker on the demo timeline: `labels.csv` has no row for either demo file.
- **New copy.** The design asks for these lines without wording them, so they were written
  here: the mic permission line, the mic-blocked, no-mic, insecure-origin and dropped
  connection status lines, the demo status lines, `Synthetic voice, replayed through the
  same pipeline.`, `Text replay, no audio`, and `First alert at {n} seconds.`

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

Added in Phase 3:

- **The session holds the sheet, the rules stay pure.** `alerts.decide` is unchanged and
  caution is still not sticky there. `CallSession` only sends an alert when the level rises.
- **One notifier per call.** A reset makes a new one, so work left over from the old call
  can never spend the new call's one push. After a reset the old call's late explainer
  answer and its scam push are both dropped; after a hang-up they finish.
- **Socket work order.** Frames are handled one at a time. Whisper and the scorer run in a
  worker thread, the alert is sent as soon as the rules raise it, and the explainer and the
  pushes run as background tasks behind one send lock.
- **Known limit of wire redaction.** A number is replaced per chunk, and a code cut across
  chunks arrives in short pieces, so length is not the test: a written digit always goes,
  and a spoken number goes at two digits. What is left is one case. When the cut leaves a
  single spoken digit alone at a chunk edge, that one word goes out as it was heard.
  Replacing every lone `one` was the other choice; it was turned down on Nov 14 because
  `no [number] called` reads as broken on the screen.
- **Whisper is on the CPU on the build laptop for now.** On Nov 14 a real decode on cuda
  failed with `cublas64_12.dll` not found, so the app fell back to cpu/int8, where a 4 s
  chunk of speech took about 0.8 s (two runs). The earlier "runs on CUDA" check decoded
  silence with the VAD on, which never reaches the GPU; preflight now decodes with it off.

## 10. Open items

- Organisation phone numbers — every entry in `server/orgs.json` needs a verified number
  and a `verified_at` date.
- The CUDA runtime libraries Whisper needs (`cublas64_12.dll` was not found on Nov 14).
  Until they are installed Whisper runs on cpu/int8. Installing them is a dependency
  decision, so it is not made in passing.
- Known limit: repetition inflates `digit_count`. Measured Nov 14 on cpu/int8. The chunker
  cuts `tts_scam.wav` at 6 s in the middle of a code being read aloud, and Whisper repeats
  itself on that slice: it returns 110 digits where a clean decode of the same audio counts
  7, and the whole read-out is 12. The warning itself is not affected, since it needs only
  6 and fires on time, but `danger.digit_count` is then not the number of digits spoken.
  So the banner shows no count (§9), and eval must not read `digit_count` as one.
  `without_timestamps=True` gave 7 digits on that slice; no further decode change is
  planned.
- The timing behind `temperature=0.0` (§4), same slice, same day. With Whisper's default
  temperature retries it took 16.6 s and 14.5 s to transcribe (two runs), against about
  0.7 s for the slices around it, and in the demo replay the code warning arrived about
  17 s after the chunk closed. With `temperature=0.0` it takes 1.9 s, 2.2 s and 1.4 s
  (three runs) and the warning arrives 1.75 s after the chunk closes.
- Kaggle API token for the cross-dataset test (Sunday only).
- A recorded demo call at `eval/calls/demo_scam.wav` and a matching row in `labels.csv`.
- The design system in `docs/design/` was authored at scaffold time, not sourced from a
  designer. Treat it as the spec anyway; changes go through this file.

## 11. Cut order when behind

Spanish → browser check → plots. Never cut the 20 recorded calls, the alert rules, or the
honest results table.
