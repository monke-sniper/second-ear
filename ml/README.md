# ml — training and baselines

Two Colab notebooks and the facts they rely on. The dataset facts were checked on Nov 14
against the files on the hub, at revision `321b961b5ae353e19ed479b960658dcd223d5e06`. Both
notebooks pin that revision.

## The dataset, as it actually is

`BothBosu/scam-dialogue` on Hugging Face. Apache-2.0. Synthetic, generated with
`meta-llama-3-70b-instruct`.

| File | Rows |
|---|---|
| `scam-dialogue_train.csv` | 1 280 |
| `scam-dialogue_test.csv` | 320 |

Columns: `dialogue`, `type`, `label`. Labels are 50/50 in both files, 8 types evenly spread.

- `label` 1 → scam: `ssn`, `refund`, `support`, `reward`.
- `label` 0 → legitimate: `delivery`, `insurance`, `telemarketing`, `wrong`.
- `dialogue` is **one string** with inline lowercase speaker tags: `caller:` and `receiver:`.
  Not `Suspect:` / `Innocent:` — strip `caller:` / `receiver:` before training, because live
  transcripts carry no labels at all.

Four things the files show that the dataset card does not:

- One training dialogue is a word-for-word copy of a test dialogue.
- One training dialogue appears twice.
- The dialogues are templated: 298 of the 320 test dialogues share their first 12 words with
  one of the 1 150 training conversations. Scores on this test split flatter any model trained
  on the train split.
- **The opening gives the label away.** Looking up a test dialogue's first 6 words among the
  training conversations and taking their majority label is right for 295 of 320, with no model.
  In the train CSV, 639 of 640 scam dialogues open with `hello`, and 384 of the 385 dialogues
  that open with `hi` are legitimate. A model can score well here by learning the greeting, and
  a real scam call that opens with "Hi" would start with a lean towards legitimate.

So both notebooks remove the leading greeting from every row (all 1 280 train and all 320 test
dialogues open with one). **That takes away the greeting, not the shortcut**: with the greeting
gone, the first 6 words still give the right label for 289 of 320 test dialogues, because the
sentence after the greeting is templated too (in the train CSV, 211 scam and no legitimate
dialogues then start with `this`; 160 legitimate and 1 scam start with `i'm`).

The training notebook recounts all of this, writes it to `model.json`, and reports two checks
on the opening under `diagnostics` (see below).

The repo never commits data. The notebooks download the CSVs from the hub.

## train_risk_model.ipynb

Training data is BothBosu only. There is no matched-pairs set in this build.

1. Load both CSVs at the pinned revision. Print columns, row counts and label balance. No
   dialogue is ever printed.
2. Strip the speaker tags, then the leading greeting: `hello`, `hi`, `hey`, `good morning` /
   `afternoon` / `evening`, plus the punctuation after it. One rule for every row and both
   labels, in train, val and test, before the split.
3. Drop the two leaking training rows (the duplicate and the copy of a test row), then split
   train into train/val by conversation, 90/10, stratified by `type`, seed 42. The given test
   CSV is the test set, untouched at 320.
4. Only then augment train and val: prefixes at 20/40/60/80/100 % of each dialogue's words,
   same label. This is how the model learns to flag early. Then, for every one of those
   examples, one copy with its first k words removed, k uniform 5 to 15 (seeded), same label,
   so the model cannot lean on the templated opening. An example of k words or fewer gets no
   copy. Train: 5 750 prefix examples + 5 728 copies = 11 478. Val: 640 + 639 = 1 279. The test
   split gets no augmentation.
5. Fine-tune `distilbert-base-uncased`: `max_length=256`, `truncation_side="left"`, 3 epochs,
   `lr=2e-5`, fp16. A plain PyTorch loop, so it needs nothing beyond torch and transformers.
   One full checkpoint goes to Drive after every epoch and the previous one is kept as a spare;
   Run all after a disconnect resumes. A checkpoint made from different settings or different
   training text is refused.
6. Metrics at P(scam) ≥ 0.5: precision, recall, F1 on the full test dialogues **and** on their
   first 40 % of words, each with its n. Nothing is tuned on test; val is only watched.
   The headline tests (`bothbosu_test_full`, `bothbosu_test_prefix40`) use the greeting-free
   text. A second pair (`..._with_greeting`) scores the original text, which training never
   saw, so the before and after sit side by side.
7. Export model + tokenizer, reload the folder on CPU to prove it scores the same, zip it.
   `model.json` is written only after that, and carries the sha256 of the exported weights.

Two diagnostics ride along in `model.json`, outside the table rows: the two headline tests with
the first 12 words of every dialogue removed, and P(scam) for six hand-written lines (a
scam-like and an everyday message, each bare, behind `hello` and behind `hi`). They show how
much the model leans on how a call opens.

The server applies the same rule. `server/scorer.py` calls `strip_greeting` from
`server/greeting.py`, a verbatim copy of the code below, once on the whole transcript from the
start of the call, after whitespace is collapsed and before the text is cut to its last 256
tokens. It removes one greeting only. `tests/test_scorer.py` pins the pattern character for
character, so **a rule change must change three places together**: the shared helpers cell of
both notebooks (and this block), `server/greeting.py`, and that test. The `..._with_greeting`
rows and the probes show what the model does when a greeting is left in.

```python
import re

GREETING_PATTERN = re.compile(
    r"^\s*(?:hello|hi|hey|good\s+(?:morning|afternoon|evening))\b[\s,.!?;:\-\u2013\u2014]*", re.IGNORECASE
)


def strip_greeting(text: str) -> str:
    """Remove one leading greeting (hello, hi, hey, good morning / afternoon / evening) and the
    punctuation after it. The same rule for every row and both labels: in this dataset the
    greeting alone nearly gives the label away."""
    return GREETING_PATTERN.sub("", text, count=1)
```

Why left truncation: the live scorer reads the most recent 256 tokens, so training must see
the same window — the tail of a conversation, not the head.

Outputs, in Drive under `MyDrive/second-ear/`:

- `risk-scorer.zip` — flat, `config.json` at the zip root. Unzip **into**
  `models/risk-scorer/` (gitignored) so that `models/risk-scorer/config.json` exists.
  `server/scorer.py` looks for that file. Until it is there the app scores with the keyword
  stand-in (`load_app_scorer`), which is a placeholder with no accuracy claim.
- `eval/results/model.json` — copy to `eval/results/model.json` in the repo.

The score is `softmax(logits)[1]`: index 1 is `SCAM`, index 0 is `LEGIT` (also in `config.json`).

## baselines.ipynb

Keyword baseline only, on the same four tests and with the same metrics as the model (the
greeting makes no difference to a phrase list; the rows are there so the tables line up).

- Phrases: `gift card`, `wire transfer`, `bitcoin`, `don't tell anyone`, `remote access`,
  `warrant`, `medicare number`. Any hit → scam.
- Matching is case-insensitive, whole phrase, plural allowed, so `warrant` does not fire on
  `warranty`. The list and the rule were fixed before the test split was scored.
- Writes `eval/results/baselines.json` when run from the repo root, else `baselines.json` in
  the working directory. No GPU, no installs.

The Haiku zero-shot baseline is not built.

## Results files

`model.json` and `baselines.json` share one shape, `second-ear/results-v1`. `rows` is the part
the results table is built from, already in the columns of `docs/SPEC.md` §8:

```json
{"test": "bothbosu_test_full", "metric": "recall", "value": 0.4, "n": 160, "notes": "n = scam dialogues; 320 scored in all; tp=64 fp=0 fn=96 tn=160; ..."}
```

`n` is each metric's own denominator: dialogues flagged as scam for precision, scam dialogues
for recall, every dialogue scored for F1. The notes say which, and always give the total.

Next to `rows`: `confusion` (tp/fp/fn/tn per test), `by_type` (n and correct per scenario
type), `caveats`, and for the model `split`, `training` (with `train_seconds`),
`test_overlap_with_training`, `diagnostics` and `export`. A metric with a zero denominator is
`null`, never 0. No dialogue text goes in either file.

## Colab notes

- T4 GPU runtime for training; the baseline runs on CPU.
- The training notebook installs one thing, and only if needed: `transformers==4.57.6`, when
  Colab's version differs. The server loads the exported folder with that version. Colab's
  image listed `transformers==5.22.1` on Nov 14 (googlecolab/backend-info), so the install
  does run; pip may warn about other preinstalled packages, which is expected.
- `train_seconds` covers training and per-epoch validation. Checkpoint writes to Drive are left
  out, so the number is the same whether or not the run was interrupted.
- `RUN_NAME` is `distilbert-prefix-v3-opencrop`, the final recipe. Checkpoints from v1 (greeting
  kept) and v2 (no opening crop) sit in their own Drive folders; they are never resumed and can
  be deleted.
- To start over instead of resuming, change `RUN_NAME` in the config cell. When every epoch is
  already in the checkpoint, the notebook says in capitals that nothing was trained and reuses
  those weights.
- Never touch the Gemini-written held-out set or the 20 improvised calls here.
