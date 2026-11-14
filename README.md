# Second Ear

A second ear on the call. The phone plays the call on speaker, this app listens, scores
scam risk as the conversation moves, and tells the person a safe line to say while pushing
one alert to a family member. Entry for the Veritas AI International High School Hackathon,
Nov 14–15 2026, AI + Health track.

**This repo is a scaffold, committed at the start of build weekend.** Every module exists
with its typed interface and contract docstring; the bodies raise `NotImplementedError`.
`pytest -q` is green: the plumbing runs (`/health`, `/ws/audio` echo, `/simulate` returns 501)
and the behaviour specs in `tests/spec_*.py` are strict-xfail so they turn green as each rule
lands. What is scaffolded and what is real is listed below.

## Status, this commit

Working now:

- `GET /health` returns `{"status": "ok"}`
- `WS /ws/audio` accepts binary PCM frames and echoes byte counts
- `python -m server.preflight` reports Python, CUDA, CTranslate2, Whisper, model and env state
- `pytest -q` — 13 passed, 29 strict-xfail specs
- `eval/run_eval.py --help` parses labels; scoring raises until Phase 6

Interface only, body raises `NotImplementedError`:

- `server/chunker.py`, `stt.py`, `scorer.py`, `alerts.py`, `danger.py`, `explainer.py`, `notify.py`
- `POST /simulate` (declared, returns 501)
- `web/*` — DOM skeleton and design tokens only, no behaviour

Not in the repo, by design:

- Model weights (`models/`), audio recordings (`eval/calls/*.wav`), `.env`
- The Kaggle cross-dataset CSV — needs a Kaggle API token, not set up yet

## Quickstart (Windows)

```bash
# one time
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
cp .env.example .env          # fill ANTHROPIC_API_KEY and NTFY_TOPIC

# every session
source .venv/Scripts/activate   # PowerShell: .venv\Scripts\Activate.ps1
python -m server.preflight      # proves CUDA + Whisper + env before you trust a demo
uvicorn server.app:app --reload --port 8000
pytest -q
```

Open `http://localhost:8000/` for the app shell, `http://localhost:8000/health` for the
health check. Enable "Demo mode" once Phase 5 lands; it replays `eval/calls/demo_scam.wav`.

## Layout

```
server/   FastAPI app, audio pipeline, alert rules, explainer, push
web/      Phone UI, plain HTML/JS, no build step
ml/       Colab notebooks: train the scorer, run baselines
eval/     Offline scoring of recorded calls, results, plots
tests/    test_* = green plumbing, spec_* = strict-xfail behaviour specs
docs/     SPEC.md (frozen contract), design/ (UI tokens + component specs)
```

## Decisions that are already made

Full list in `docs/SPEC.md`. The ones that shape everything:

- Audio is raw 16 kHz mono s16le PCM in 250 ms frames. Never MediaRecorder webm chunks —
  only the first chunk has a header, the rest fail to decode.
- Chunks are cut at pauses into 2–6 s pieces, never on a fixed grid, so words stay whole.
- Whisper is `base.en` on CUDA via CTranslate2. torch stays CPU: the scorer is 66M params
  and scores in ~30 ms, training happens in Colab.
- Risk 0..1 from DistilBERT over the last 256 tokens, left-truncated to match live input.
- Caution at smoothed 0.5; scam at two consecutive chunks above 0.85; scam is sticky for
  the rest of the call.
- Spoken digits are normalized and counted, never stored, logged, or sent. The decision
  carries a count, nothing else.
- Haiku names the scam and the organisation from a fixed list, 4 s budget, validated,
  and can never change the alert level.
- One ntfy push per alert type per call.

## Known gaps before Saturday 6 PM

- `server/orgs.json` has names and aliases but `phone: null` for every entry. Phase 0 asked
  for numbers checked on each organisation's own site; that has not been done. Do not invent
  them — fill them from the official pages and set `verified_at`.
- No Kaggle credentials yet (needed only for the cross-dataset test on Sunday).
- No recorded demo call yet (`eval/calls/demo_scam.wav`).

## Credits

Built during the hackathon with Claude Code. Libraries: FastAPI, uvicorn, faster-whisper,
CTranslate2, transformers, PyTorch, Anthropic SDK, ntfy. Data: BothBosu/scam-dialogue on
Hugging Face (Apache-2.0, synthetic, generated with meta-llama-3-70b-instruct). Full credits
with links land in the submission write-up.

This is a prototype that can miss scams. It is not a guarantee, and it never touches the
call itself.
