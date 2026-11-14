# Second Ear

A second ear on the call. The phone plays the call on speaker, this app listens, scores
scam risk as the conversation moves, and tells the person a safe line to say while pushing
one alert to a family member. Entry for the Veritas AI International High School Hackathon,
Nov 14–15 2026, AI + Health track.

**This repo started as a scaffold at the start of build weekend and is being filled in phase
by phase.** Every module has a typed interface and a contract docstring; the ones not built
yet raise `NotImplementedError`. `pytest -q` is green: the server pipeline runs end to end
(`/health`, `/ws/audio`, `/simulate`) and the behaviour specs in `tests/spec_*.py` pass
for every rule that has landed. What is real and what is still interface-only is listed below.

## Status, this commit

Working now:

- `GET /health` returns `{"status": "ok"}`
- `WS /ws/audio` takes binary PCM frames, acks each one, and streams transcript, risk,
  alert, danger and explainer events (`server/live.py`, `pipeline.py`)
- `POST /simulate` replays text chunks through the same pipeline and never sends a push
- `python -m server.preflight` reports Python, CUDA, CTranslate2, Whisper, model and env state
- The chunker, Whisper (`stt.py`, with a CPU fallback), the alert rules (`alerts.py`), the
  code warning (`danger.py`, `numbers.py`), the Haiku explainer (`explainer.py` and its two
  helpers) and the family push (`notify.py`)
- A keyword stand-in scorer, so alerts fire before the trained model exists. It is a
  placeholder with no accuracy claim, not a result
- `pytest -q` — 159 passed, no xfail left (the tests use fakes for Whisper, Haiku and ntfy)
- `python scripts/smoke_explainer.py` and `python scripts/smoke_push.py` check the real
  Haiku request and a real push once `.env` has the key and the topic
- `eval/run_eval.py --help` parses labels; scoring raises until Phase 6

Interface only, body raises `NotImplementedError`:

- `web/*` — DOM skeleton and design tokens only, no behaviour
- `eval/run_eval.py` scoring

Not there yet, and the app says so instead of pretending: the trained scorer
(`models/risk-scorer/`), an Anthropic key (the explainer returns its generic line without
one), and the CUDA libraries Whisper needs on the build laptop (it runs on the CPU until then).

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

Open `http://localhost:8000/` for the app, `http://localhost:8000/health` for the health
check. The mic only works on localhost or https. `http://localhost:8000/?demo=1` is the demo
console: it replays `eval/calls/demo_scam.wav` through the same socket with the mic off, or
the synthetic-voice `tts_scam.wav` if there is no recording, or a scripted text replay if
there is neither.

## Layout

```
server/   FastAPI app, audio pipeline, alert rules, explainer, push
web/      Phone UI, plain HTML/JS, no build step
ml/       Colab notebooks: train the scorer, run baselines
eval/     Offline scoring of recorded calls, results, plots
tests/    test_* = green plumbing, spec_* = behaviour specs (strict-xfail until built)
scripts/  smoke checks you run by hand against the real Haiku API and ntfy
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
