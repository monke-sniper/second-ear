# OfficialNumberCard

Callback verification: who the caller says they are, and the number that organisation actually
publishes. This is what turns "hang up" into "hang up and call back safely".

## Anatomy

```
CALL BACK                     ← label, muted
Medicare                      ← org name, body, 600
1-800-633-4227                ← number, title, tabular figures
Checked on medicare.gov       ← caption, muted   (only when source is known)
```

- Label: `CALL BACK` (copy key `call_back`).
- Org name: from `server/orgs.json`, matched on the explainer's `claimed_org`.
- Number: `official_number` from the same entry. `title` size, tabular figures, `tel:` link on
  touch devices, plain text on desktop.
- Source line: the organisation's domain from `source_url`, so the number is checkable.

## Unknown organisation

When `org` is null — no match, explainer degraded, or numbers not verified yet:

```
CALL BACK
Use the number on your card
or your last statement.
```

No numeral is shown, and no guessed number is ever rendered. A wrong number here sends someone
to a scammer, which is strictly worse than no number.

## States

| State | Shows |
|---|---|
| matched + verified | org, number, source domain |
| matched + unverified (`phone: null`) | org name, `Use the number on your card or your last statement.` |
| unmatched | the unknown block above |
| explainer degraded | the unknown block above |

## Accessibility

- The whole card is one link on touch (`tel:`), with `aria-label` = "Call Medicare at
  1-800-633-4227".
- Tabular figures so the number does not shift as it loads.
- Minimum 24 px for the number; it is the second-biggest text on the screen after the line.

## Don't

- Don't render a number that has no `verified_at` in `orgs.json`.
- Don't format numbers differently from the organisation's own site.
- Don't hide the card when the org is unknown; the instruction to use the card still matters.
