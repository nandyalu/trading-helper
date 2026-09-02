# The mark

The logo for **The Allowance**.

**TA, drawn as an equity curve.**

One horizontal rule runs the width of the mark. It is the T's top bar and the A's crossbar at once, and it is the baseline — the money the agent started with, the same line the equity chart measures against.

The T's stem drops below it in red. The A rises above it in green. Down then up, in the two colours the rest of the site uses for exactly that, so TA reads three ways at once: The Allowance, the TradingAgents framework this is built on, and the thing being measured.

The corner brackets are two things at once: the guardrails the agent cannot pass, and a viewfinder, because the point of the experiment is that it is under observation.

## Which file to use

| File | For |
|---|---|
| `logo-light.svg` | Light backgrounds |
| `logo-dark.svg` | Dark backgrounds |
| `logo-mono.svg` | One ink. Inherits `currentColor`, so it works anywhere colour cannot be relied on — print, a stamp, a forced-colours mode |
| `logo-badge.svg` | Boxed on dark, for an avatar or a social profile |
| `../favicon.svg` | The browser tab |

**In the Angular app, use `<app-logo>` rather than any of these.** The component takes its colours from the theme tokens, so it follows the light and dark palettes without a second file to keep in step. These exist for everywhere the app is not: a README, a post, a slide.

## Rules

- **Do not recolour the T and the A.** Red below the line and green above it is the whole idea. Use `logo-mono.svg` when one ink is needed.
- **Do not remove the brackets.** They are the guardrails, and the mark says nothing without them.
- **Do not set it below 16px.** The letterforms stop resolving. Checked at 16, 24, 32, 64 and 160.
- Leave clear space of about a quarter of the mark's width on every side.
