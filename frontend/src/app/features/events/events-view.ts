import { DatePipe, DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';

import { AgentEvent } from '../../core/models/api.models';
import { AgentService } from '../../core/services/agent.service';

/**
 * Every decision pass, with the prompt and the answer verbatim.
 *
 * The Auto trader page shows what the agent holds. This shows how it decided,
 * which is a different question and the one that is hard to reconstruct later:
 * behaviour here is mostly prompt, so a month of runs across three prompt
 * revisions cannot be told apart without the words each run actually saw.
 *
 * The prompt and the answer are collapsed by default. A prompt runs to tens of
 * kilobytes, and a feed that opens with one is a feed nobody scrolls.
 */
@Component({
  selector: 'app-events-view',
  standalone: true,
  imports: [DatePipe, DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './events-view.html',
})
export class EventsView {
  private readonly agent = inject(AgentService);
  readonly events = this.agent.events;
  readonly loading = signal(true);
  /** Which panels are open, keyed `${id}:prompt` / `${id}:response`. */
  private readonly open = signal<Set<string>>(new Set());

  constructor() {
    void this.agent.loadEvents().finally(() => this.loading.set(false));
  }

  isOpen(id: number, which: 'prompt' | 'response'): boolean {
    return this.open().has(`${id}:${which}`);
  }

  toggle(id: number, which: 'prompt' | 'response'): void {
    const next = new Set(this.open());
    const key = `${id}:${which}`;
    next.has(key) ? next.delete(key) : next.add(key);
    this.open.set(next);
  }

  /** A pass that asked nothing has no words to show — the market was shut, or
   * the agent was switched off. Saying so beats an empty panel. */
  asked(event: AgentEvent): boolean {
    return !!event.prompt;
  }

  did(event: AgentEvent): string {
    if (event.skipped) return event.skipped;
    if (!event.orders.length) return 'nothing';
    return event.orders.map((o) => `${o.side} ${o.ticker}`).join(', ');
  }
}
