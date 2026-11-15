# The recorded calls: briefs and rules

The 12 calls listed in `labels.csv` were each improvised from a one-line brief. This file
holds the brief each call started from. The audio itself is not in the repo.

## Rules

- Each call was improvised from one line, the brief below.
- Every number said on a call (a code, a card number, an amount) is made up.
- Everyone recorded agreed to be recorded.
- The calls were scored once, by `eval/run_eval.py`. The results are in
  `eval/results/calls.json`, and the calls the system got wrong are in
  `eval/results/failures.md`.

## Briefs

The file numbers are not consecutive. These 12 are every call that was recorded and scored.

| file | label | brief |
|---|---|---|
| `01_pharmacy.wav` | legitimate | \<BRIEF\> |
| `02_grandparent.wav` | scam (grandparent) | \<BRIEF\> |
| `03_doctor.wav` | legitimate | \<BRIEF\> |
| `04_medicare.wav` | scam (medicare) | \<BRIEF\> |
| `05_bank_real.wav` | legitimate | \<BRIEF\> |
| `06_tech_support.wav` | scam (tech_support) | \<BRIEF\> |
| `07_grandkid_40.wav` | legitimate | \<BRIEF\> |
| `08_fake_bank_code.wav` | scam (bank_fraud) | \<BRIEF\> |
| `09_insurance.wav` | legitimate | \<BRIEF\> |
| `12_prize_code.wav` | scam (reward) | \<BRIEF\> |
| `14_romance.wav` | scam (romance) | \<BRIEF\> |
| `17_dentist.wav` | legitimate | \<BRIEF\> |
