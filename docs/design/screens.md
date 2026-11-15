# Screens

Six screens, designed at 360 × 640 first. Every one is read at a glance by someone who may be
scared, hard of hearing, and holding a phone in one hand.

## 1 · Ready

What the person sees before anything is happening.

- Title `Second Ear`, one line under it: `Put the call on speaker next to this phone.` The
  name is the quiet one (`label` size, muted); the line under it is the loud one (`body`
  size, 600 weight, ink), on every screen.
- RiskMeter at 0, word `Calm`.
- Primary button `Start listening` (56 px, full width). Secondary text button `Demo mode`.
  The buttons sit at the bottom of the screen, under the thumb; `Stop` takes the same place.
- Empty transcript area with the placeholder `The call will appear here.`
- First run only: a line explaining the mic permission prompt, no modal.

Acceptance: fits 360 × 640 without scrolling; the start button is reachable with a thumb.

## 2 · Listening

The call is live and nothing is wrong yet.

- RiskMeter updating on `risk` events, band per the meter spec.
- Latest two transcript lines, `body` size, muted, truncated at two lines each.
- `Stop` button replaces `Start listening`, neutral outline.
- Status line: `Listening.` — never a spinner.

Acceptance: the score changing does not move the transcript block; no layout shift.

## 3 · Caution

Risk crossed 0.50, nothing conclusive yet.

- AlertSheet opens in `caution` state: amber header `▲ Be careful`.
- SafeExitCard at `title` size with the default line.
- OfficialNumberCard present; unknown org shows the card-or-statement line.
- `This is a real call` button, 56 px.
- RiskMeter visible behind the scrim is not interactive.

Acceptance: `SAY THIS` and `CALL BACK` both visible without scrolling at 360 × 640.

## 4 · Scam alert

Two chunks over 0.85. This is the screen the demo lives on.

- AlertSheet in `scam` state: red header `■ This sounds like a scam`.
- SafeExitCard at `display` size — the largest text in the app.
- OfficialNumberCard with the matched organisation and its number.
- DangerBanner appears above everything the moment digits are detected; it is never inside the
  sheet.
- `This is a real call` remains the only button.

Acceptance: the safe-exit line and the callback number are both readable at arm's length
without scrolling, in under two seconds of looking.

## 5 · Real call (neutral)

The person pressed `This is a real call`.

- Sheet closes; page returns to the listening layout.
- RiskMeter switches to `neutral` styling with the word `Real call` and a `●`.
- A muted line under it: `Marked as a real call. Alerts are off for this call.`
- DangerBanner is **not** affected: digits still fire the code warning.
- `Stop` stays where it was.

Acceptance: one tap gets here; nothing animates for more than 180 ms.

## 6 · Demo console

The judges' view (`/?demo=1`), built for a two-minute walkthrough.

- First thing on the console, in a bordered notice: `Nothing here is live. The mic is off in
  demo mode.` It sits above the reach of the alert sheet. With the banner and the scam sheet
  both up, its second row can be covered.
- Recording card: file name and `Play` / `Replay` on one row, and under them the label
  `Recorded call, replayed through the same pipeline.`
- Transcript column and RiskMeter side by side (still inside 360 px, stacked).
- A 12 px timeline under the meter with a marker where the first alert fired and where the
  money ask is in the recording. The marker is a bar with a pointer on top, not a colour
  alone.

## Wide screens

From 600 px wide, the column is one 360 × 640 panel (`surface`, `radius.lg`,
`elevation.sheet`) on a `neutral.base` backdrop. The DangerBanner and the scrim stay inside
the panel; neither spans the window. This is what a screen recording shows. On a phone
nothing changes.

Acceptance: plays `eval/calls/demo_scam.wav` end to end after a page reload; visible proof the
mic is off.

## Not screens

- No settings screen, no login, no onboarding carousel.
- No history list. After `reset`, yesterday's call is gone on purpose.
