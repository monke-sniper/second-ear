# Results

Built by `python -m eval.run_eval` from: `baselines.json`, `heldout.json`.
Every number is copied from its results file. `n` is that metric's own denominator.

## keyword (baselines.json, 2026-11-14T20:32:55Z)

| test | metric | value | n | notes |
|---|---|---|---|---|
| bothbosu_test_full | precision | 1.0 | 64 | n = dialogues flagged as scam; 320 scored in all; tp=64 fp=0 fn=96 tn=160; leading greeting removed, as for the model; scam is the positive class; any listed phrase present |
| bothbosu_test_full | recall | 0.4 | 160 | n = scam dialogues; 320 scored in all; tp=64 fp=0 fn=96 tn=160; leading greeting removed, as for the model; scam is the positive class; any listed phrase present |
| bothbosu_test_full | f1 | 0.5714 | 320 | n = dialogues scored; 320 scored in all; tp=64 fp=0 fn=96 tn=160; leading greeting removed, as for the model; scam is the positive class; any listed phrase present |
| bothbosu_test_prefix40 | precision | 1.0 | 46 | n = dialogues flagged as scam; 320 scored in all; tp=46 fp=0 fn=114 tn=160; first 40 % of words; leading greeting removed, as for the model; scam is the positive class; any listed phrase present |
| bothbosu_test_prefix40 | recall | 0.2875 | 160 | n = scam dialogues; 320 scored in all; tp=46 fp=0 fn=114 tn=160; first 40 % of words; leading greeting removed, as for the model; scam is the positive class; any listed phrase present |
| bothbosu_test_prefix40 | f1 | 0.4466 | 320 | n = dialogues scored; 320 scored in all; tp=46 fp=0 fn=114 tn=160; first 40 % of words; leading greeting removed, as for the model; scam is the positive class; any listed phrase present |
| bothbosu_test_full_with_greeting | precision | 1.0 | 64 | n = dialogues flagged as scam; 320 scored in all; tp=64 fp=0 fn=96 tn=160; original text with its greeting; scam is the positive class; any listed phrase present |
| bothbosu_test_full_with_greeting | recall | 0.4 | 160 | n = scam dialogues; 320 scored in all; tp=64 fp=0 fn=96 tn=160; original text with its greeting; scam is the positive class; any listed phrase present |
| bothbosu_test_full_with_greeting | f1 | 0.5714 | 320 | n = dialogues scored; 320 scored in all; tp=64 fp=0 fn=96 tn=160; original text with its greeting; scam is the positive class; any listed phrase present |
| bothbosu_test_prefix40_with_greeting | precision | 1.0 | 46 | n = dialogues flagged as scam; 320 scored in all; tp=46 fp=0 fn=114 tn=160; first 40 % of words; original text with its greeting; scam is the positive class; any listed phrase present |
| bothbosu_test_prefix40_with_greeting | recall | 0.2875 | 160 | n = scam dialogues; 320 scored in all; tp=46 fp=0 fn=114 tn=160; first 40 % of words; original text with its greeting; scam is the positive class; any listed phrase present |
| bothbosu_test_prefix40_with_greeting | f1 | 0.4466 | 320 | n = dialogues scored; 320 scored in all; tp=46 fp=0 fn=114 tn=160; first 40 % of words; original text with its greeting; scam is the positive class; any listed phrase present |

## keyword-stand-in (heldout.json, 2026-11-14T23:51:50Z)

Scorer: the keyword stand-in, not a trained model.

| test | metric | value | n | notes |
|---|---|---|---|---|
| gemini_heldout_full | precision | 0.96 | 25 | n = dialogues flagged as scam; 100 scored in all; tp=24 fp=1 fn=26 tn=49; scam is the positive class; app scorer keyword-stand-in, score >= 0.5 |
| gemini_heldout_full | recall | 0.48 | 50 | n = scam dialogues; 100 scored in all; tp=24 fp=1 fn=26 tn=49; scam is the positive class; app scorer keyword-stand-in, score >= 0.5 |
| gemini_heldout_full | f1 | 0.64 | 100 | n = dialogues scored; 100 scored in all; tp=24 fp=1 fn=26 tn=49; scam is the positive class; app scorer keyword-stand-in, score >= 0.5 |
| gemini_heldout_prefix40 | precision | 1.0 | 9 | n = dialogues flagged as scam; 100 scored in all; tp=9 fp=0 fn=41 tn=50; first 40 % of words; scam is the positive class; app scorer keyword-stand-in, score >= 0.5 |
| gemini_heldout_prefix40 | recall | 0.18 | 50 | n = scam dialogues; 100 scored in all; tp=9 fp=0 fn=41 tn=50; first 40 % of words; scam is the positive class; app scorer keyword-stand-in, score >= 0.5 |
| gemini_heldout_prefix40 | f1 | 0.3051 | 100 | n = dialogues scored; 100 scored in all; tp=9 fp=0 fn=41 tn=50; first 40 % of words; scam is the positive class; app scorer keyword-stand-in, score >= 0.5 |

## keyword (heldout.json, 2026-11-14T23:51:50Z)

| test | metric | value | n | notes |
|---|---|---|---|---|
| gemini_heldout_full | precision | 0.9412 | 17 | n = dialogues flagged as scam; 100 scored in all; tp=16 fp=1 fn=34 tn=49; scam is the positive class; any listed phrase present |
| gemini_heldout_full | recall | 0.32 | 50 | n = scam dialogues; 100 scored in all; tp=16 fp=1 fn=34 tn=49; scam is the positive class; any listed phrase present |
| gemini_heldout_full | f1 | 0.4776 | 100 | n = dialogues scored; 100 scored in all; tp=16 fp=1 fn=34 tn=49; scam is the positive class; any listed phrase present |
| gemini_heldout_prefix40 | precision | 0.8333 | 6 | n = dialogues flagged as scam; 100 scored in all; tp=5 fp=1 fn=45 tn=49; first 40 % of words; scam is the positive class; any listed phrase present |
| gemini_heldout_prefix40 | recall | 0.1 | 50 | n = scam dialogues; 100 scored in all; tp=5 fp=1 fn=45 tn=49; first 40 % of words; scam is the positive class; any listed phrase present |
| gemini_heldout_prefix40 | f1 | 0.1786 | 100 | n = dialogues scored; 100 scored in all; tp=5 fp=1 fn=45 tn=49; first 40 % of words; scam is the positive class; any listed phrase present |
