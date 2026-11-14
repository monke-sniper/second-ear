# ml — training and baselines

Two Colab notebooks and the facts they need. Both are created in Phase 2; this file is the
brief and the dataset truth, verified on Nov 14 against the files themselves.

## The dataset, as it actually is

`BothBosu/scam-dialogue` on Hugging Face. Apache-2.0. Synthetic, generated with
`meta-llama-3-70b-instruct`.

| File | Rows |
|---|---|
| `scam-dialogue_train.csv` | 1 280 |
| `scam-dialogue_test.csv` | 320 |

Columns: `dialogue`, `type`, `label`.

- `label` 1 → scam: `ssn`, `refund`, `support`, `reward`.
- `label` 0 → legitimate: `delivery`, `insurance`, `telemarketing`, `wrong`.
- `dialogue` is **one string** with inline lowercase speaker tags: `caller:` and `receiver:`.
  Not `Suspect:` / `Innocent:` — strip `caller:` / `receiver:` before training, because live
  transcripts carry no labels at all.

A local copy lives outside the repo at `C:/Users/idkch/AI-Models/data/bothbosu/`; the repo
never commits data.

## train_risk_model.ipynb — required output

1. Split by conversation into train/val/test **before** any augmentation. Use the given test
   split as the test split.
2. Strip speaker tags.
3. Augment train and val only: prefixes at 20/40/60/80/100 % of each dialogue's words, same
   label. This is how the model learns to flag early.
4. Fine-tune `distilbert-base-uncased`: `max_length=256`, `truncation_side="left"`, 3 epochs,
   `lr=2e-5`, fp16, checkpoint to Drive every epoch.
5. Metrics: precision, recall, F1 on full test dialogues **and** on 40 % prefixes; write
   `eval/results/model.json` with the counts (n) next to every metric.
6. Export the model + tokenizer as a folder that drops into `models/risk-scorer/` (gitignored).
   `server/scorer.py` looks for `config.json` in that folder and uses `StubScorer` until it
   exists.

Why left truncation: the live scorer reads the most recent 256 tokens, so training must see
the same window — the tail of a conversation, not the head.

## baselines.ipynb — required output

On the same held-out test split:

- Keyword list: `gift card`, `wire transfer`, `bitcoin`, `don't tell anyone`, `remote access`,
  `warrant`, `medicare number`. Score with the same metrics.
- Haiku zero-shot: label each test dialogue SCAM / LEGIT as JSON, same metrics.
- Write `eval/results/baselines.json`, same schema as `model.json`.

## Colab notes

- GPU runtime; install `transformers==4.57.6`, `datasets`, `accelerate`, `scikit-learn`.
- Drive mount, checkpoint every epoch — a disconnect must cost one epoch, not the run.
- Record wall-clock training time; it goes in the results table.
- Never touch the Gemini-written held-out set or the 20 improvised calls here.
