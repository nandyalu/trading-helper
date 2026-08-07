import { Component, computed, input } from '@angular/core';

/** Decisions that read as "get in" versus "get out". Anything else — Hold, or
 * the REVIEW the model emits when its own rating did not parse — is amber:
 * neither a reason to buy nor a reason to sell. */
const BUYISH = new Set(['buy', 'overweight']);
const SELLISH = new Set(['sell', 'underweight']);

@Component({
  selector: 'app-decision-badge',
  template: `<span class="badge" [class]="tone()">{{ decision() }}</span>`,
})
export class DecisionBadge {
  readonly decision = input.required<string>();

  protected readonly tone = computed(() => {
    const decision = this.decision().toLowerCase();
    if (BUYISH.has(decision)) return 'badge-pos';
    if (SELLISH.has(decision)) return 'badge-neg';
    return 'badge-warn';
  });
}
