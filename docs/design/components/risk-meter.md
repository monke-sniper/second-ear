# RiskMeter

The always-visible answer to "how worried should I be right now". Small, steady, legible from
a metre away. It never demands attention; the AlertSheet does that.

## Anatomy

```
┌──────────────────────────────┐
│  ●  Calm                 12  │   word + shape on the left, score on the right
│  ▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░  │   bar, 8px tall, full width of the card
└──────────────────────────────┘
```

- Word: `Calm` / `Watch` / `Scam` — `label` size, 600 weight.
- Shape: `●` calm, `▲` watch, `■` scam, 16 px, before the word.
- Score: integer 0–100, `title` size, tabular figures, right-aligned.
- Bar: track `color.neutral.soft`, fill uses the band's `base`.

## States

| Band | Score | Colour | Word | Shape |
|---|---|---|---|---|
| calm | 0–49 | `calm` | Calm | ● |
| watch | 50–84 | `watch` | Watch | ▲ |
| scam | 85–100 | `scam` | Scam | ■ |

Bands are display-only. The alert logic lives on the server (`alerts.py`), not here; the meter
shows whatever `risk` event arrived.

## Sizes

Full width of the content column, min height 72 px. Bar 8 px, radius `pill`. Number never
smaller than 28 px.

## Accessibility

- Container: `role="meter"`, `aria-valuemin="0"`, `aria-valuemax="100"`, `aria-valuenow`,
  `aria-valuetext="Scam, 92 out of 100"`.
- The word is not decorative; screen readers get the band, not just the number.
- Contrast: each band's `ink` on its `soft` is 8.2:1 or better.

## Don't

- Don't animate the number upward between events; update on events only.
- Don't show decimals.
- Don't flash, pulse, or shake at high risk. The alert is the loud part.
