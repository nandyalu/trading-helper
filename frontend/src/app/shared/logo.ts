import { Component, input } from '@angular/core';

/**
 * The mark: **TA**, drawn as an equity curve inside its bounds.
 *
 * One horizontal rule runs the width of the mark. It is the T's top bar and
 * the A's crossbar at once, and it is the baseline — the money the agent
 * started with, the same line the equity chart measures against.
 *
 * The T's stem drops below it. The A rises above it. Down then up, in the two
 * colours the rest of the site uses for exactly that, so the initials of the
 * framework this is built on also read as the thing being measured.
 *
 * The corner brackets are the guardrails, and a viewfinder: the point of the
 * experiment is that it is under observation.
 *
 * Drawn on a 32-unit grid. At favicon size the frame and the baseline survive
 * and the letterforms become texture, which still reads as "something
 * contained".
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

      <!-- The bounds. Corners only: a closed box reads as a container, open
           corners read as limits, which is the truer statement. -->
      <g
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
        stroke-linejoin="round"
        [attr.opacity]="frameOpacity()"
      >
        <path d="M2.5 9.5V4.3A1.8 1.8 0 0 1 4.3 2.5H9.5" />
        <path d="M22.5 2.5h5.2a1.8 1.8 0 0 1 1.8 1.8v5.2" />
        <path d="M29.5 22.5v5.2a1.8 1.8 0 0 1-1.8 1.8h-5.2" />
        <path d="M9.5 29.5H4.3a1.8 1.8 0 0 1-1.8-1.8v-5.2" />
      </g>

      <!-- The A, above the line. Drawn first so the baseline sits over the
           point where the legs cross it. -->
      <path
        d="M17 23.5 21.5 8.5 26 23.5"
        [attr.stroke]="up()"
        stroke-width="2.4"
        stroke-linecap="round"
        stroke-linejoin="round"
      />

      <!-- The T, below it. -->
      <path d="M10 15.5V23.5" [attr.stroke]="down()" stroke-width="2.4" stroke-linecap="round" />

      <!-- The baseline: the T's bar, the A's crossbar, and where the agent
           started, all one stroke. -->
      <path d="M6 15.5H26" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" />
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
  /** Empty on a decorative instance beside text that already says it. */
  readonly label = input<string>('');
  /** The frame is quieter than the letterforms at large sizes and needs its
   * full weight at small ones, where it is most of what survives. */
  readonly frameOpacity = input<number>(0.55);
  readonly up = input<string>('var(--pos)');
  readonly down = input<string>('var(--neg)');
}
