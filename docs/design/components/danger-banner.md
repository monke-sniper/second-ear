# DangerBanner

The code warning. It exists because the person is about to read a card number, a gift-card
code, or a Social Security number out loud, and that is the last moment anything can be done.

## When it fires

Server sends `danger` when 6 or more spoken digits land within a 10 s window while risk is
above 0.50, or after a scam alert is already active. It fires instantly and does not wait for
the explainer.

## Anatomy

Full-bleed band pinned to the top of the viewport, above the AlertSheet, `z-index` top.

```
┌──────────────────────────────────────┐
│  ■  Do not read that number out      │   title, white on scam.base
│     Hang up, then call back on a     │   body, white on scam.base
│     number you know.                 │
└──────────────────────────────────────┘
```

- Background `color.scam.base`, text `color.scam.on`.
- Title `title` size, body `body` size. No icon button, no close control.
- It stays until the call is reset. There is no dismiss.

## Copy (fixed)

- Title: `Do not read that number out`
- Body: `Hang up, then call back on a number you know.`

## Accessibility

- `role="alert"`, `aria-live="assertive"`, mounted once and never re-announced.
- Its two lines are written into it at the moment it shows, and it is empty while hidden.
  A screen reader announces a live region when its text changes; words that were already
  there when the page loaded could go unsaid.
- The banner never contains the digits that triggered it. Screen readers must not hear them
  either.
- Contrast: white on `scam.base` is 6.5:1.

## Don't

- Don't show the detected digits, not even masked.
- Don't make it dismissible.
- Don't stack a second banner; repeat detections keep the same banner and increment a counter
  that is not displayed.
