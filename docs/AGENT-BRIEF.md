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

## Commands

From the repo root. Git Bash:

    source .venv/Scripts/activate
    uvicorn server.app:app --reload --port 8000
    pytest -q
    python -m server.preflight          # proves CUDA, Whisper, model files, env before a demo

PowerShell: `.venv\Scripts\Activate.ps1`

Dependencies: `uv pip install -r requirements.txt`. Never add a dependency without adding it
to `requirements.in` and recompiling `requirements.txt` (`uv pip compile requirements.in
-o requirements.txt --python-version 3.11`).

## Rules

- IMPORTANT: never commit secrets. Keys live in `.env`; `.env.example` documents them.
- IMPORTANT: spoken digits are never stored, logged, or sent. `danger.py` returns counts only.
  Do not print transcripts that contain them, do not put them in exception messages.
- Run `pytest -q` after every change and show me the output.
- One job per module. Keep files under ~200 lines; split rather than grow.
- Start every new file with 3 plain-English lines: what it does, what it does not do.
- A behaviour change updates `docs/SPEC.md` in the same commit.
- Live transcripts have no speaker labels. Training text must not either.
- The Haiku model id lives in `server/config.py` only. Use `settings.haiku_model`.
- Commit after each phase gate passes. One phase, one commit.

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

## Phase gates

1. Scaffold — this commit.
2. Model — `ml/train_risk_model.ipynb` produces `models/risk-scorer/` and `eval/results/model.json`.
3. Streaming — speak, see transcript; `/simulate` returns a timeline; its tests pass.
4. Alerts — `spec_alerts`, `spec_danger`, `spec_explainer`, `spec_notify` go green as implemented.
5. Frontend — a full live call works 3× in a row; demo mode plays a recorded file.
6. Eval — `eval/run_eval.py` writes `eval/results/table.md`, two plots, `failures.md`.
7. Write-up, video, submit.

Cut order when behind: Spanish, browser check, plots. Never cut the 20 recorded calls or the
alert rules.

## Preferences

- Typed signatures, docstrings that state the contract, no clever one-liners.
- Errors degrade, never crash: an explainer or push failure must leave the alert standing.
- Plain human copy in the UI. No exclamation marks, no "Oops".
