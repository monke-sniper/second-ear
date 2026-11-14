# AlertSheet

The moment the app earns its place: a full-screen answer to "what do I say, who do I call".

## When it opens

On an `alert` event. `caution` → amber header, `scam` → red header. It replaces whatever was
on screen; it never opens twice. If a caution escalates to scam, the same sheet rewrites its
header and copy in place.

## Anatomy

```
┌──────────────────────────────────────┐  scrim: rgba(15,23,42,0.60)
│ ┌──────────────────────────────────┐ │  sheet: card, radius lg top
│ │  ▲ Be careful                    │ │  header band, level colour, white text
│ ├──────────────────────────────────┤ │
│ │  SAY THIS                        │ │  SafeExitCard
│ │  I'll call you back at the       │ │
│ │  number on my card.              │ │
│ ├──────────────────────────────────┤ │
│ │  CALL BACK                       │ │  OfficialNumberCard
│ │  Medicare                        │ │
│ │  1-800-633-4227                  │ │
│ ├──────────────────────────────────┤ │
│ │  [ This is a real call ]         │ │  56px, full width, neutral
│ └──────────────────────────────────┘ │
└──────────────────────────────────────┘
```

- Header band: `scam.base` or `watch.base`, title `This sounds like a scam` / `Be careful`,
  `title` size, `on` colour. Includes the band shape (`■` / `▲`) before the text.
- Body order is fixed: SafeExitCard, then OfficialNumberCard, then the neutral action.
- One button only: `This is a real call`. The app cannot end the call — the call is on the
  other phone — so there is no "hang up" button that would lie.

## States

| State | Header | Body | Button |
|---|---|---|---|
| caution | amber, `Be careful` | safe-exit + callback | `This is a real call` |
| scam | red, `This sounds like a scam` | safe-exit + callback | `This is a real call` |
| dismissed | none | screen returns to neutral | — |

Dismissing marks the call as legitimate for the rest of the call: the meter goes neutral grey
with the word `Real call`, and **the danger banner stays armed** — a scammer who talked their
way past the alert can still ask for a code.

The explainer can arrive late and update the safe-exit line, the scam type and the callback
number while the sheet is open. A late failure leaves the generic line; the sheet never closes
because the API failed.

## Accessibility

- `role="dialog"`, `aria-modal="true"`, `aria-labelledby` points at the header title.
- Focus moves to the header title when it opens; the button is the first tab stop.
- The sheet is the only scrollable region; the page behind does not scroll.
- Header and body text at least 4.5:1; the neutral button uses `neutral.base` on `card`.
- Reduced motion: the sheet appears instantly, no slide.

## Don't

- Don't show the transcript, the score, or the digits in the sheet.
- Don't put two buttons side by side; a stressed person mis-taps.
- Don't word the neutral action as "Ignore" or "It's fine" — `This is a real call` is the fact
  being asserted, not a judgement of the app.
