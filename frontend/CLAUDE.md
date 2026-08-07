# frontend — Claude Code context

Angular 22 (standalone components, signals, zoneless), vitest for tests, `lightweight-charts` for both charts. No UI framework and no CSS preprocessor: `src/styles.css` is the whole design system. Commands run from `frontend/`: `npx ng build` (full template type-check), `npx ng test`, `npx prettier --write "src/**/*.{ts,html,css}"`.

## Styling rules

**Feature templates carry no styling of their own.** They compose the classes in `src/styles.css`. A component gets a `styles:` block only when the style depends on something the global sheet cannot see — the two chart components size their own canvas that way, and nothing else should need it. This is what stops a table on `/signals` and a table on `/portfolio` from drifting apart, so resist adding a one-off rule to a component when a shared class would do.

**Colors come from the tokens at the top of `src/styles.css`, never as literals.** The exception is `COLORS` in `shared/price-chart.ts` and the matching `.dot` rules in the stylesheet: those draw to a canvas, and the comment on each side says to keep them in step.

**Two themes, always.** The dark palette is declared twice — once under `prefers-color-scheme` for readers who never touch the toggle, once under `:root[data-theme='dark']` for readers who did. CSS cannot share one block between a media query and an attribute selector, so a new token has to be added in both places. `index.html` sets `data-theme` in an inline script before the first paint; do not move that into Angular or dark readers get a white flash on every load.

Canvas cannot inherit a CSS variable. Both charts read the tokens through `shared/chart-theme.ts` at creation and again on every theme change; a new chart must do the same or its axis labels stay the wrong color until reload.

## Layout, and what breaks on a phone

Three breakpoints, all in `src/styles.css`:

- **≥1024px** — fixed sidebar, `.content` offset by `--sidebar-w`.
- **<1024px** — the same `.sidebar` element becomes a slide-in drawer, plus a sticky `.topbar`. A closed drawer is `visibility: hidden`, not merely translated off-screen, so its links stay out of the tab order.
- **<640px** — a bottom `.tabbar` of the four primary destinations plus a button that opens the drawer for the rest. Every route must stay reachable from the drawer; `app.spec.ts` asserts it.

**A new table needs `class="data-table data-table--stack"`, a `data-label` on every `<td>`, and a `.table-wrap` around it.** Below 640px the rows become labelled blocks built from those `data-label` values; a cell without one renders as a value with no name. Use `data-label=""` for the ticker cell and for action cells, which are self-explanatory. Six columns side-scrolling off a phone screen hides the column that matters, which is why stacking is the default rather than the fallback.

## What the pages are for

`overview` is the landing page and the only one that ranks by urgency: the "needs a decision" block comes first and is the one block on the page with a red border, because everything else is context. Keep that hierarchy — a second attention-colored block on the page destroys the signal.

Loading states use `.skeleton` at the shape of the content that will replace them, so the layout does not jump. Empty states use `.empty` and say both what would appear there and how to make it appear; "No data" on its own is not enough.
