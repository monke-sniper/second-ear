# Results

Built by `python -m eval.run_eval` from: `model.json`, `baselines.json`, `heldout.json`, `calls.json`.
Every number is copied from its results file. `n` is that metric's own denominator.

## distilbert (model.json, 2026-11-15T00:18:23Z)

| test | metric | value | n | notes |
|---|---|---|---|---|
| bothbosu_test_full | precision | 0.9938 | 161 | n = dialogues flagged as scam; 320 scored in all; tp=160 fp=1 fn=0 tn=159; leading greeting removed, as in training; scam is the positive class; P(scam) >= 0.5; 256 tokens, left-truncated |
| bothbosu_test_full | recall | 1.0 | 160 | n = scam dialogues; 320 scored in all; tp=160 fp=1 fn=0 tn=159; leading greeting removed, as in training; scam is the positive class; P(scam) >= 0.5; 256 tokens, left-truncated |
| bothbosu_test_full | f1 | 0.9969 | 320 | n = dialogues scored; 320 scored in all; tp=160 fp=1 fn=0 tn=159; leading greeting removed, as in training; scam is the positive class; P(scam) >= 0.5; 256 tokens, left-truncated |
| bothbosu_test_prefix40 | precision | 1.0 | 160 | n = dialogues flagged as scam; 320 scored in all; tp=160 fp=0 fn=0 tn=160; first 40 % of words; leading greeting removed, as in training; scam is the positive class; P(scam) >= 0.5; 256 tokens, left-truncated |
| bothbosu_test_prefix40 | recall | 1.0 | 160 | n = scam dialogues; 320 scored in all; tp=160 fp=0 fn=0 tn=160; first 40 % of words; leading greeting removed, as in training; scam is the positive class; P(scam) >= 0.5; 256 tokens, left-truncated |
| bothbosu_test_prefix40 | f1 | 1.0 | 320 | n = dialogues scored; 320 scored in all; tp=160 fp=0 fn=0 tn=160; first 40 % of words; leading greeting removed, as in training; scam is the positive class; P(scam) >= 0.5; 256 tokens, left-truncated |
| bothbosu_test_full_with_greeting | precision | 0.9938 | 161 | n = dialogues flagged as scam; 320 scored in all; tp=160 fp=1 fn=0 tn=159; original text with its greeting, which training never saw; scam is the positive class; P(scam) >= 0.5; 256 tokens, left-truncated |
| bothbosu_test_full_with_greeting | recall | 1.0 | 160 | n = scam dialogues; 320 scored in all; tp=160 fp=1 fn=0 tn=159; original text with its greeting, which training never saw; scam is the positive class; P(scam) >= 0.5; 256 tokens, left-truncated |
| bothbosu_test_full_with_greeting | f1 | 0.9969 | 320 | n = dialogues scored; 320 scored in all; tp=160 fp=1 fn=0 tn=159; original text with its greeting, which training never saw; scam is the positive class; P(scam) >= 0.5; 256 tokens, left-truncated |
| bothbosu_test_prefix40_with_greeting | precision | 1.0 | 160 | n = dialogues flagged as scam; 320 scored in all; tp=160 fp=0 fn=0 tn=160; first 40 % of words; original text with its greeting, which training never saw; scam is the positive class; P(scam) >= 0.5; 256 tokens, left-truncated |
| bothbosu_test_prefix40_with_greeting | recall | 1.0 | 160 | n = scam dialogues; 320 scored in all; tp=160 fp=0 fn=0 tn=160; first 40 % of words; original text with its greeting, which training never saw; scam is the positive class; P(scam) >= 0.5; 256 tokens, left-truncated |
| bothbosu_test_prefix40_with_greeting | f1 | 1.0 | 320 | n = dialogues scored; 320 scored in all; tp=160 fp=0 fn=0 tn=160; first 40 % of words; original text with its greeting, which training never saw; scam is the positive class; P(scam) >= 0.5; 256 tokens, left-truncated |
| training | train_seconds | 243.5 | 11478 | Tesla T4, fp16=True, 3 epochs; training and validation, checkpoint writes excluded; n = training examples; resumed=False |

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

## distilbert (heldout.json, 2026-11-15T00:25:06Z)

| test | metric | value | n | notes |
|---|---|---|---|---|
| gemini_heldout_full | precision | 0.7679 | 56 | n = dialogues flagged as scam; 100 scored in all; tp=43 fp=13 fn=7 tn=37; scam is the positive class; app scorer distilbert, score >= 0.5 |
| gemini_heldout_full | recall | 0.86 | 50 | n = scam dialogues; 100 scored in all; tp=43 fp=13 fn=7 tn=37; scam is the positive class; app scorer distilbert, score >= 0.5 |
| gemini_heldout_full | f1 | 0.8113 | 100 | n = dialogues scored; 100 scored in all; tp=43 fp=13 fn=7 tn=37; scam is the positive class; app scorer distilbert, score >= 0.5 |
| gemini_heldout_prefix40 | precision | 0.6667 | 57 | n = dialogues flagged as scam; 100 scored in all; tp=38 fp=19 fn=12 tn=31; first 40 % of words; scam is the positive class; app scorer distilbert, score >= 0.5 |
| gemini_heldout_prefix40 | recall | 0.76 | 50 | n = scam dialogues; 100 scored in all; tp=38 fp=19 fn=12 tn=31; first 40 % of words; scam is the positive class; app scorer distilbert, score >= 0.5 |
| gemini_heldout_prefix40 | f1 | 0.7103 | 100 | n = dialogues scored; 100 scored in all; tp=38 fp=19 fn=12 tn=31; first 40 % of words; scam is the positive class; app scorer distilbert, score >= 0.5 |

## keyword (heldout.json, 2026-11-15T00:25:06Z)

| test | metric | value | n | notes |
|---|---|---|---|---|
| gemini_heldout_full | precision | 0.9412 | 17 | n = dialogues flagged as scam; 100 scored in all; tp=16 fp=1 fn=34 tn=49; scam is the positive class; any listed phrase present |
| gemini_heldout_full | recall | 0.32 | 50 | n = scam dialogues; 100 scored in all; tp=16 fp=1 fn=34 tn=49; scam is the positive class; any listed phrase present |
| gemini_heldout_full | f1 | 0.4776 | 100 | n = dialogues scored; 100 scored in all; tp=16 fp=1 fn=34 tn=49; scam is the positive class; any listed phrase present |
| gemini_heldout_prefix40 | precision | 0.8333 | 6 | n = dialogues flagged as scam; 100 scored in all; tp=5 fp=1 fn=45 tn=49; first 40 % of words; scam is the positive class; any listed phrase present |
| gemini_heldout_prefix40 | recall | 0.1 | 50 | n = scam dialogues; 100 scored in all; tp=5 fp=1 fn=45 tn=49; first 40 % of words; scam is the positive class; any listed phrase present |
| gemini_heldout_prefix40 | f1 | 0.1786 | 100 | n = dialogues scored; 100 scored in all; tp=5 fp=1 fn=45 tn=49; first 40 % of words; scam is the positive class; any listed phrase present |

## distilbert (calls.json, 2026-11-15T14:58:49Z)

| test | metric | value | n | notes |
|---|---|---|---|---|
| recorded_calls | catch_rate | 0.6667 | 6 | n = scam calls; caught = any alert, caution or scam; 4 caught, 2 missed; 12 calls in all; scorer distilbert |
| recorded_calls | catch_rate_scam_level | 0.6667 | 6 | n = scam calls; only a scam-level alert counts; 12 calls in all; scorer distilbert |
| recorded_calls | false_alarm_rate | 0.1667 | 6 | n = legitimate calls; any alert, caution or scam; 1 alerted; 12 calls in all; scorer distilbert |
| recorded_calls | false_alarm_rate_scam_level | 0.1667 | 6 | n = legitimate calls; only a scam-level alert counts; 12 calls in all; scorer distilbert |
| recorded_calls | median_seconds_to_first_alert | 22.5 | 4 | n = scam calls that raised an alert; audio time at the end of the chunk that raised the alert; a live call adds the decode time; 12 calls in all; scorer distilbert |
| recorded_calls | alerted_before_money_ask | n/a | 0 | n = scam calls with a money_ask_s in labels.csv; first alert strictly before it; 12 calls in all; scorer distilbert |
| recorded_calls | danger_fired_rate | 0.5 | 6 | n = scam calls; the digit warning fired; 12 calls in all; scorer distilbert |
| recorded_calls | danger_fired_rate_legitimate | 0.0 | 6 | n = legitimate calls; the digit warning fired; 12 calls in all; scorer distilbert |
