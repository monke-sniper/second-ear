# eval

Measures the frozen system. Nothing here changes detection, and nothing here is imported by
the server. Run every command from the repo root, in the `.venv`.

| Command | What it does | Writes |
|---|---|---|
| `python -m eval.make_heldout --check` | asks Google whether the Gemini model in `.env` is available | nothing |
| `python -m eval.make_heldout` | writes the held-out set, once | `eval/heldout/gemini.jsonl`, `gemini.meta.json` |
| `python -m eval.score_heldout` | scores it with the app scorer and the keyword baseline | `eval/results/heldout.json` |
| `python -m eval.run_eval --dry-run` | runs every call in `calls/labels.csv` and prints the result | nothing |
| `python -m eval.run_eval --dry-run --file eval/calls/x.wav --label 1` | one wav that is not in `labels.csv` | nothing |
| `python -m eval.run_eval` | the real run over the recorded calls, once | `eval/results/calls.json`, `failures.md`, `table.md` |
| `python -m eval.run_eval --table-only` | rebuilds the table from the results files that exist | `eval/results/table.md` |

## Rules

- **The scorer is whatever the app loads** (`load_app_scorer()`): the trained model when
  `models/risk-scorer/` exists, else the keyword stand-in. Every results file says which in
  its `scorer` block, and says so in `caveats` when it was the stand-in.
- **The held-out set is written once.** The brief in `heldout_brief.py` was committed before
  the first request. The generator checks format only and runs no scorer, so no transcript
  was kept or dropped for being easy or hard. It refuses to overwrite the set.
- **The recorded calls are scored once**, after detection freezes. `run_eval` refuses to run
  again while `calls.json` exists. Use `--dry-run` to try the tooling.
- **Caught means any alert, caution or scam.** A false alarm is any alert on a legitimate
  call. Both are also reported at scam level. Alert times are audio time at the end of the
  chunk that raised the alert; a live call adds the decode time.
- **No transcript text in any results file.** `failures.md` has short snippets with every
  number replaced.
- Recordings are 16 kHz mono 16-bit wav. Anything else is refused with the ffmpeg line that
  converts it. See `calls/README.md` for how to record one.
- Plots are not built. `calls.json` keeps each call's risk timeline.
