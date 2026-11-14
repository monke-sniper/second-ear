# Second Ear — agent brief

> This is the intended content of `CLAUDE.md`. The write to `CLAUDE.md` needs the repo
> owner's approval (agent-instruction file), so it lives here until that approval lands.
> Nothing else changes: Claude Code should read this file first either way.

# Second Ear

Scam-call interrupter for the Veritas AI hackathon, Nov 14–15 2026. It listens to a call on
speakerphone, scores scam risk live, tells the person a safe way to end the call, and pushes
one alert to a family member before money moves.

This repo is a scaffold. Every module exists with its typed interface and contract docstring;
the bodies raise `NotImplementedError`. `pytest -q` is green because the plumbing works
(`/health`, `/ws/audio` echo) and the behaviour specs in `tests/spec_*.py` are strict-xfail.
Your job is to replace bodies, phase by phase, and delete each xfail marker as its rule lands.

Read `docs/SPEC.md` before changing behaviour. It is the frozen contract: thresholds, windows,
wire messages, data rules. If the code and SPEC disagree, SPEC wins unless I say otherwise.

## The four rules

1. **Numbers are verified, never recalled.** Phone numbers, metrics, contrast ratios,
   thresholds. If it is not in a file or on the organisation's own site, it does not go in.
2. **Frozen things change by editing `docs/SPEC.md` and its test in the same commit** — not
   by editing a constant and hoping nobody notices.
3. **Stop and ask before: a new dependency, a wire-shape change, a phone number, anything
   published, or deleting an xfail marker.** Those five moves are what cost the weekend.
4. **Digits never leave the call.** No digit run in a log, an exception, a prompt, a push, or
   a test failure message. Errors degrade; they never take the alert down.

## Commands

From the repo root. Git Bash:

    source .venv/Scripts/activate
    uvicorn server.app:app --reload --port 8000
    pytest -q
    python -m server.preflight          # proves sys.path, CUDA, Whisper, model files, env

PowerShell: `.venv\Scripts\Activate.ps1`

Dependencies: `uv pip install -r requirements.txt`. Never add a dependency without adding it
to `requirements.in` and recompiling `requirements.txt` (`uv pip compile requirements.in
-o requirements.txt --python-version 3.11`).

Scaffold state, for orientation: `pytest -q` is 13 passed / 29 xfailed, `/health` answers,
`/ws/audio` acks byte counts, `/simulate` returns 501, Whisper `base.en` runs on CUDA at about
100 ms per second of audio, and `StubScorer` returns 0.0 until `models/risk-scorer/` exists.

## Layout

| Path | Owns |
|---|---|
| `server/app.py` | FastAPI wiring: `/health`, `/ws/audio`, `/simulate`, static web |
| `server/contracts.py` | Every wire message. Change here first, then the code |
| `server/chunker.py` | 250 ms frames in, 2–6 s pause-cut chunks out |
| `server/stt.py` | PCM chunk in, English text out (faster-whisper) |
| `server/scorer.py` | Transcript in, risk 0..1 out (DistilBERT; stub until trained) |
| `server/alerts.py` | Score history in, alert decision out (pure functions) |
| `server/danger.py` | Transcript + risk in, digit-warning decision out |
| `server/explainer.py` | Alert in, named scam + safe-exit line + org out (Haiku) |
| `server/notify.py` | One ntfy push per alert type per call |
| `server/orgs.json` | Fixed organisation list; numbers verified from official sites |
| `web/` | Phone UI, plain HTML/JS, no build step. `docs/design/` is the spec |
| `ml/` | Colab notebooks: train the scorer, run baselines |
| `eval/` | Offline scoring of recorded calls, results table, plots |
| `tests/` | `test_*` = green plumbing. `spec_*` = strict-xfail behaviour specs |

## Things that need eyes

Some of this repo cannot be checked by running it. It needs a person, or a source.

### Ask me first — do not decide alone

| Move | Why it needs me |
|---|---|
| Add or remove a dependency | `requirements.txt` is a compiled lock proven by a real install; a new dep invalidates that proof |
| Change a number in SPEC §2 (0.5 / 0.85 / 6 digits / 10 s / 4 s / 2–6 s / 256 tokens) | it is the contract the spec tests pin, and finalists get questioned on it |
| Change a field or a `type` in `server/contracts.py` | the browser, `/simulate` and the tests all speak it; silent drift breaks the demo |
| Delete an `xfail` marker | only after its tests pass for real — an early delete hides a broken rule |
| Put a phone number anywhere | a wrong callback number sends someone to a scammer; that is worse than no number |
| Edit copy in `docs/design/` (`SAY THIS`, `CALL BACK`, `Be careful`, `This sounds like a scam`) | it is the readable half of the safety feature |
| Push, publish, change repo visibility, record or upload the video | the submission rules are one shot |
| Touch a recording | consent from everyone audible, every time |

### Verify from the source, never from memory

| Claim | Source of truth |
|---|---|
| An organisation's phone number | that organisation's own site → set `phone` + `source_url` + `verified_at` together. A test fails you if a phone appears without the other two. |
| A metric (F1, catch rate, seconds to alert) | `eval/results/*.json`, quoted with its `n`. If the JSON has no number, the sentence does not get one. |
| A contrast ratio | measure it with the WCAG formula; the values in `docs/design/tokens.json` were measured, not eyeballed |
| Dataset shape and speaker tags | the CSV. Tags are inline `caller:` / `receiver:`, **not** `Suspect:` / `Innocent:` — the weekend plan is wrong there, `docs/SPEC.md` §6 is right |
| The Haiku model id | `server/config.py` only |
| A threshold or window | `alerts.py` / `danger.py` constants, which mirror SPEC §2. If they disagree, SPEC wins and the constant is the bug. |
| Whether this machine can run it | `python -m server.preflight`, never "it worked earlier" |

### Traps that already cost hours here

- **A foreign `site-packages` kills the process before any diagnostic prints.** A spawned shell
  can inherit conda's `PYTHONPATH`, and then numpy dies with
  `No module named 'numpy._core._multiarray_umath'`. `preflight` checks `sys.path` before
  importing anything third-party — run it first, and keep its top-level imports stdlib-only.
- **torch is CPU on purpose.** Whisper gets the GPU through CTranslate2.
  `torch.cuda.is_available() == False` is the expected state, not a bug to fix.
- **`vad_filter=True` always.** Without it, silence becomes invented words like "thank you"
  and the transcript is poisoned.
- **Raw PCM, never `MediaRecorder`.** Only the first webm chunk carries a header; the rest do
  not decode. The worklet sends 8 000-byte frames of 16 kHz mono s16le.
- **The first Whisper load pays CUDA init and the model download** (about 15 s here). Call
  `warmup()` before a demo, or the first chunk looks like a hang.
- **MSYS shell quirks.** `/dev/null` is not translated for native tools — use `NUL`. Native
  tools need `C:/...` paths; MSYS path conversion is off.
- **`hf_xet` is not installed**, so model downloads use plain HTTP. Slower; harmless. Do not
  stop to fix it mid-build.

### Before you say done

- [ ] `pytest -q` is green: `test_*` pass, `spec_*` are xfail only for what is still unbuilt
- [ ] every rule you implemented has its marker deleted **and** its tests still pass
- [ ] `docs/SPEC.md` matches the code you just wrote
- [ ] `python -m server.preflight` says OK
- [ ] no digit run in any log line, exception, prompt or push payload
- [ ] `git status` / `git diff` show no secret, key or ntfy topic
- [ ] the demo path still works: a recorded file replays through the same pipeline

## Phase gates

1. Scaffold — the current commit.
2. Model — `ml/train_risk_model.ipynb` produces `models/risk-scorer/` and `eval/results/model.json`.
3. Streaming — speak, see transcript; `/simulate` returns a timeline; its tests pass.
4. Alerts — `spec_alerts`, `spec_danger`, `spec_explainer`, `spec_notify` go green as implemented.
5. Frontend — a full live call works 3× in a row; demo mode plays a recorded file.
6. Eval — `eval/run_eval.py` writes `eval/results/table.md`, two plots, `failures.md`.
7. Write-up, video, submit.

Cut order when behind: Spanish, browser check, plots. Never cut the 20 recorded calls or the
alert rules.

## Working rules

- Run `pytest -q` after every change and show me the output.
- One job per module. Keep files under ~200 lines; split rather than grow.
- Start every new file with 3 plain-English lines: what it does, what it does not do.
- Commit after each phase gate passes. One phase, one commit.
- Never commit secrets. `.env` is gitignored; `.env.example` documents the keys.
- Live transcripts have no speaker labels, so training text must not either.
- Typed signatures, docstrings that state the contract, no clever one-liners.
- Errors degrade, never crash: an explainer or push failure must leave the alert standing.
- Plain human copy in the UI. No exclamation marks, no "Oops".
