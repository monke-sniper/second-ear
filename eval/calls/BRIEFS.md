# The recorded calls: briefs and rules

The 12 calls listed in `labels.csv` were each improvised from a one-line brief. This file
holds the brief each call started from. The audio itself is not in the repo.

## Rules

- Each call was improvised from the one-line brief below. The note under the table says
  what changed from call 06 on.
- Every number said on a call (a code, a card number, an amount) is made up.
- Everyone recorded agreed to be recorded.
- The calls were scored once, by `eval/run_eval.py`. The results are in
  `eval/results/calls.json`, and the calls the system got wrong are in
  `eval/results/failures.md`.

## Briefs

The file numbers are not consecutive. These 12 are every call that was recorded and scored.

| file | label | brief |
|---|---|---|
| `01_pharmacy.wav` | legitimate | Pharmacy: prescription is ready; confirm date of birth before pickup. |
| `02_grandparent.wav` | scam (grandparent) | Grandson in jail after a car accident; needs bail in gift cards; don't tell his parents. |
| `03_doctor.wav` | legitimate | Doctor's office confirming Tuesday's appointment; bring insurance card. |
| `04_medicare.wav` | scam (medicare) | "Medicare" says a new card is coming; needs the Medicare number to activate it. |
| `05_bank_real.wav` | legitimate | Real bank fraud team: did you make a $500 charge? Says they'll never ask for a PIN; call the number on your card. |
| `06_tech_support.wav` | scam (tech_support) | "Microsoft" found a virus; asks them to install an app so they can fix it remotely. |
| `07_grandkid_40.wav` | legitimate | Real grandkid asks for $40 for pizza tonight, will pay back, mom knows. |
| `08_fake_bank_code.wav` | scam (bank_fraud) | "Chase fraud department" texted a code; asks them to read it back; 12 made-up digits read aloud. |
| `09_insurance.wav` | legitimate | Insurance renewal reminder; reads a made-up policy number aloud. |
| `12_prize_code.wav` | scam (reward) | Won a car; pay $300 in fees with a gift card; read the card code aloud (12 made-up digits). |
| `14_romance.wav` | scam (romance) | Slow burn: online friend overseas, sweet talk first; only near the end needs money for a plane ticket. |
| `17_dentist.wav` | legitimate | Dentist reminder for a cleaning; reads a made-up office callback number aloud. |

Calls 01–05 were improvised from the one-line brief. From call 06 on, Dad also had three
short beats (who he is, what he pushes, how it ends) and still used his own words.
