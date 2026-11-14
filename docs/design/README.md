# Second Ear design system

The UI spec for `web/`. Written at scaffold time so Phase 5 has something concrete to build
against; it is not a designer's handoff. `tokens.json` is canonical for values, the component
files are canonical for anatomy and copy, `screens.md` is canonical for what each screen shows.

## How to use it

1. Copy the token values into `web/styles.css` as CSS custom properties on `:root`. Names map
   one-to-one: `color.scam.base` → `--color-scam-base`. Do not restyle by eye; if a value is
   wrong, change `tokens.json` and the CSS together.
2. Build the five components in the order they appear on screen: RiskMeter, DangerBanner,
   AlertSheet, SafeExitCard, OfficialNumberCard.
3. Design at 360 × 640 first. Wider screens center the column at 360 px; nothing reflows into
   a second column.
4. Copy strings are fixed. They are the readable half of the safety feature; changing one is a
   SPEC change.

## Rules that outrank taste

- **Readable at a glance, at arm's length.** Body 20 px, alert title 32 px, the line to say
  32–44 px. If a label and a value compete, the value wins.
- **Colour is never the only signal.** Each risk band carries a word and a shape: calm `●`,
  watch `▲`, scam `■`.
- **One alert at a time.** The DangerBanner sits above the AlertSheet; nothing else stacks.
- **Labels never drop.** "Say this" and "Call back" appear on every alert screen, at every
  phone size. If the layout cannot fit them, the layout is wrong.
- **No motion that delays the message.** Transitions are 120–180 ms, and `prefers-reduced-motion`
  turns them into instant state changes.
- **Nothing bounces, winks, or congratulates.** The person may be mid-scam; the UI stays calm.
- **No dark patterns.** Dismissing an alert ("This is a real call") never disarms the digit
  warning.

## Type

System font stack, no download, no FOUT — the demo may run offline. Sizes from
`type.scale`. Numbers in meters and phone numbers use tabular figures so a rising score does
not jitter the layout.

## Content voice

Short sentences, present tense, no jargon, no exclamation marks. Second person, imperative
when it is an instruction ("Say this", "Call back"). Never blame the person ("You may have
been tricked" is banned; "This sounds like a scam" is the ceiling).

## Language

English first. A Spanish string table is optional and only if the weekend is on track; the
structure is one dictionary of copy keys in `app.js`, so adding `es` is a data change, not a
layout change. When Spanish lands, the labels keep the same visual weight — no smaller text for
the second language.
