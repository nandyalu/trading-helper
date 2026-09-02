import { Component, input } from '@angular/core';

/**
 * The mark: a path that moves freely inside a frame it never crosses.
 *
 * The experiment in one image. The corner brackets are two things at once —
 * the guardrails the agent cannot pass, and a viewfinder, because the whole
 * point is that this is under observation. The line inside is the equity curve:
 * it wanders, it falls, it recovers, and it stays in bounds.
 *
 * Deliberately not a robot, a brain or a candlestick. The first two say "AI
 * product" and the third says "trading product", and this is neither — it is a
 * record of something being tried.
 *
 * Drawn on a 32-unit grid with `currentColor`, so it inherits ink in both
 * themes and stays legible at 20px in the nav and at 200px in the hero. The
 * brackets are the heavier stroke: at favicon size the frame survives and the
 * line becomes texture, which still reads as "something contained".
 */
@Component({
  selector: 'app-logo',
  template: `
    <svg
      [attr.width]="size()"
      [attr.height]="size()"
      viewBox="0 0 32 32"
      fill="none"
      role="img"
      [attr.aria-label]="label()"
    >
      @if (label()) {
        <title>{{ label() }}</title>
      }
      <!-- The bounds. Corners only: a closed box reads as a container, and
           open corners read as limits, which is the truer statement. -->
      <g
        stroke="currentColor"
        [attr.stroke-width]="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        opacity="0.9"
      >
        <path d="M3 10V4.8A1.8 1.8 0 0 1 4.8 3H10" />
        <path d="M22 3h5.2A1.8 1.8 0 0 1 29 4.8V10" />
        <path d="M29 22v5.2a1.8 1.8 0 0 1-1.8 1.8H22" />
        <path d="M10 29H4.8A1.8 1.8 0 0 1 3 27.2V22" />
      </g>
      <!-- The agent. Never touches the frame. -->
      <path
        d="M7.5 20.5 11 16l3 3.2 3.5-7 3 5.4 4-6.1"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
  `,
  styles: `
    :host {
      display: inline-flex;
      line-height: 0;
    }
  `,
})
export class Logo {
  readonly size = input<number>(24);
  /** Empty on a decorative instance sitting beside text that already says it. */
  readonly label = input<string>('');
}
