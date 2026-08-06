import { Component, computed, input } from '@angular/core';

@Component({
  selector: 'app-decision-badge',
  template: `<span class="badge" [class]="cssClass()">{{ decision() }}</span>`,
  styles: `
    .badge {
      display: inline-block;
      padding: 0.15rem 0.6rem;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.02em;
      white-space: nowrap;
    }
    .buy, .overweight {
      background: color-mix(in srgb, #1a7f37 18%, transparent);
      color: #1a7f37;
    }
    .hold {
      background: color-mix(in srgb, #9a6700 18%, transparent);
      color: #9a6700;
    }
    .sell, .underweight {
      background: color-mix(in srgb, #cf222e 18%, transparent);
      color: #cf222e;
    }
  `,
})
export class DecisionBadge {
  readonly decision = input.required<string>();
  protected readonly cssClass = computed(() => this.decision().toLowerCase());
}
