# Tests

Two kinds, deliberately split.

| File | What it is | Expected state |
|---|---|---|
| `test_health.py` | `/health`, the app shell, static assets | green |
| `test_ws_protocol.py` | bytes in, counted acks out, unknown events error | green |
| `test_contracts_import.py` | frame size, frozen thresholds, wire strictness, honest org table | green |
| `spec_alerts.py` | the alert rules from SPEC §2 and §4 | green since Phase 4 |
| `spec_danger.py` | digit counting, the risk gate, the pharmacy case | green since Phase 4 |
| `spec_explainer.py` | Haiku contract, redaction, validation, degradation, the 4 s budget | green since Phase 4 |
| `spec_notify.py` | one attempt per type, no digits, re-arm on reset | green since Phase 4 |

`spec_*` files are the acceptance criteria, written before the code. A spec for a feature
that does not exist yet carries a module-level `pytest.mark.xfail(strict=True)`, so:

- while the feature is missing, the failure is expected and `pytest -q` stays green;
- the moment the feature works, that file becomes `XPASS(strict)` — a **failure** — which is
  the signal to delete the marker and commit the feature.

The four Phase 4 specs have had their markers deleted. Do not weaken a spec test to make it
pass. If a spec is wrong, change `docs/SPEC.md` and the test together, in the same commit.

The specs use fakes for Haiku and ntfy, so they prove the rules, not the network. The real
request and the real push are checked by hand with `python scripts/smoke_explainer.py` and
`python scripts/smoke_push.py` once `.env` has the key and the topic.

New assertions compare counts and booleans, so a failing test never prints a digit run.

Helpers live in `tests/helpers.py` (`ScriptedScorer`, `silence_frame`, `tone_frame`, `chunk`).
