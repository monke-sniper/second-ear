# SafeExitCard

The single line the person says out loud. This is the biggest text on the screen, because it is
the only thing they have to do in the next five seconds.

## Anatomy

```
SAY THIS                      ← label, ink, bold, 18px, letter-spaced caps
I'll call you back at the     ← the line, 32–44px, 600 weight, scam.ink
number on my card.
```

- Label: `SAY THIS` (copy key `say_this`; rendered uppercase, `label` size, bold, `ink`).
- Line: server's `safe_exit_line`, `display` size on scam, `title` size on caution. Max 3
  lines at 360 px; the server already caps it at 160 characters, so anything longer is a bug
  upstream, not a CSS problem. A line that needs more than 3 lines steps down: `display` →
  `title` → 28 px, stopping at the first size that fits. So the scam screen's line is never
  smaller than the caution screen's. The default line shows at `title` size on both.
- Lines break evenly (`text-wrap: balance`), so no word sits alone on the last row.
- Quotation marks are not decoration; the line is what to say, so it is set as a quote with a
  4 px left rule in the band's `base`.

## Content rules

- Default: `I'll call you back at the number on my card.`
- The explainer may replace it with something specific (`I'm not giving that to you. I'll call
  the bank myself.`), but the validator rejects digits, anything over 160 characters, and
  anything empty. On rejection the default stands.
- Never mention the app ("Second Ear says…"). The person says the line; the app is not part of
  the conversation.

## States

| State | Text | Size |
|---|---|---|
| caution | default or explainer line | `title` 32 |
| scam | default or explainer line | `display` 44, or `title` 32 when 44 needs more than 3 lines |
| explainer degraded | default line, no visible error | same |

## Accessibility

- The line is a `<blockquote>` with `cite` removed; screen readers announce the card label
  first (`aria-labelledby` → `SAY THIS`).
- The left rule is not the only cue; the label carries the meaning.
- No italics; they cost legibility at this size.

## Don't

- Don't truncate with an ellipsis. If the line does not fit, the font size steps down, to
  `title` and then to 28 px, and stays at the first size that fits.
- Don't put the line in a button or make it copyable-looking. It is speech, not an action.
