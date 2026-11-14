# Tests

Two kinds, deliberately split.

| File | What it is | Expected state |
|---|---|---|
| `test_health.py` | `/health`, the app shell, static assets | green |
| `test_ws_protocol.py` | bytes in, counted acks out, unknown events error | green |
| `test_contracts_import.py` | frame size, frozen thresholds, wire strictness, honest org table | green |
| `spec_alerts.py` | the alert rules from SPEC §2 | strict-xfail |
| `spec_danger.py` | digit counting, the risk gate, the pharmacy case | strict-xfail |
| `spec_explainer.py` | Haiku contract, redaction, validation, degradation | strict-xfail |
| `spec_notify.py` | one push per type, no digits, re-arm on reset | strict-xfail |

`spec_*` tests fail on purpose. They are the acceptance criteria for Phases 3–4 written
before the code. Each file carries a module-level `pytest.mark.xfail(strict=True)`, so:

- while the feature is missing, the failure is expected and `pytest -q` stays green;
- the moment the feature works, that file becomes `XPASS(strict)` — a **failure** — which is
  the signal to delete the marker and commit the feature.

Do not delete a marker before its tests pass for real, and do not weaken a spec test to make
it pass. If a spec is wrong, change `docs/SPEC.md` and the test together, in the same commit.

Helpers live in `tests/helpers.py` (`ScriptedScorer`, `silence_frame`, `tone_frame`, `chunk`).
