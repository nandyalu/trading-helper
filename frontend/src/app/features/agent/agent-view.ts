import { UpperCasePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AgentTrade } from '../../core/models/api.models';
import { AgentService } from '../../core/services/agent.service';

@Component({
  selector: 'app-agent-view',
  imports: [RouterLink, UpperCasePipe],
  templateUrl: './agent-view.html',
})
export class AgentView {
  private readonly agentService = inject(AgentService);
  protected readonly book = this.agentService.book;
  protected readonly trades = this.agentService.trades;
  protected readonly performance = this.agentService.performance;
  protected readonly history = this.agentService.history;

  protected readonly running = signal(false);
  protected readonly message = signal<string | null>(null);

  /** Orders still waiting on the open. Shown apart from the rest because they
   * have moved no money yet — a pending buy has not spent its cash. */
  protected readonly pending = computed(() =>
    this.trades().filter((t) => t.status === 'pending' && !t.is_stop),
  );

  /** Stops and take-profits resting at the broker. Listed apart from pending
   * orders because they are supposed to sit unfilled — that is the job. */
  protected readonly restingStops = computed(() =>
    this.trades().filter((t) => t.status === 'pending' && t.is_stop),
  );

  constructor() {
    void this.agentService.load();
  }

  protected async runNow(): Promise<void> {
    this.running.set(true);
    this.message.set(null);
    try {
      const run = await this.agentService.runNow();
      const parts: string[] = [];
      if (run.placed.length) parts.push(`${run.placed.length} order(s) placed`);
      if (run.rejected.length) parts.push(`${run.rejected.length} rejected`);
      // Failures were previously left out entirely, so an order the broker
      // refused rendered as "No trades" — the agent looked idle when it had in
      // fact decided and been turned down.
      if (run.failed.length) {
        const why = run.failed[0].why ?? 'the broker refused it';
        parts.push(`${run.failed.length} failed at the broker (${why})`);
      }
      this.message.set(
        parts.length ? `${parts.join(', ')}. ${run.reasoning}` : `No trades. ${run.reasoning}`,
      );
    } catch (err) {
      const detail = (err as { error?: { detail?: string } })?.error?.detail;
      this.message.set(detail ?? "Couldn't run the agent.");
    } finally {
      this.running.set(false);
    }
  }

  /** Signed percentage against the budget, so the row reads the same way as
   * the equity tile above it. */
  protected returnPct(equity: number, budget: number): string {
    if (!budget) return '—';
    const pct = (equity / budget - 1) * 100;
    return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
  }

  /** Date and time, trimmed to the minute. Empty for a position still open —
   * a blank exit is the signal that it has not been sold. */
  protected when(value: string | null): string {
    return value ? value.replace('T', ' ').slice(0, 16) : '—';
  }

  protected money(value: number | null): string {
    return value === null ? '—' : `$${value.toFixed(2)}`;
  }

  protected signed(value: number | null): string {
    if (value === null) return '—';
    return `${value >= 0 ? '+' : ''}$${value.toFixed(2)}`;
  }

  protected whenPlaced(trade: AgentTrade): string {
    return (trade.filled_at ?? trade.placed_at).replace('T', ' ').slice(0, 16);
  }
}
