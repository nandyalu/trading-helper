import { Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { SignalDetail } from '../../core/models/api.models';
import { SignalsService } from '../../core/services/signals.service';
import { DecisionBadge } from '../../shared/decision-badge';

@Component({
  selector: 'app-signal-detail',
  imports: [RouterLink, DecisionBadge],
  templateUrl: './signal-detail.html',
})
export class SignalDetailPage {
  /** Why this analysis happened, in plain words.
   *
   * A signal produced because the stock just moved sharply is the analyst
   * reacting to a move the price already holds. A scheduled one is not
   * reacting to anything. Those deserve different weight, and the agent is
   * shown the same distinction in its own prompt.
   */
  protected whyItRan(trigger: string): string {
    return (
      {
        sweep: 'The normal morning run over the whole watchlist',
        commissioned: 'The agent paid for it and asked to see it the same day',
        move: 'The stock moved unusually, so this reacts to a move already in the price',
        earnings: 'The company reports earnings soon',
        manual: 'Run by hand, outside the schedule',
      }[trigger] ?? trigger
    );
  }

  private readonly route = inject(ActivatedRoute);
  private readonly signalsService = inject(SignalsService);

  protected readonly signalDetail = signal<SignalDetail | null>(null);

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.signalDetail.set(await this.signalsService.getDetail(id));
  }

  protected reportKeys(reports: Record<string, string>): string[] {
    return Object.keys(reports);
  }

  /** Whether the trader stated any of the trade plan. Every field is optional
   * on its schema, so an older signal or a vague proposal can have none. */
  protected hasTradePlan(s: SignalDetail): boolean {
    return (
      s.entry_price !== null ||
      s.stop_loss !== null ||
      s.win_probability !== null ||
      s.risk_reward !== null ||
      s.expected_value_r !== null
    );
  }

  /** Whether the run was measured at all. Signals recorded before the columns
   * existed have none of it, and an unmeasured run must not render as free. */
  protected hasRunCost(s: SignalDetail): boolean {
    return s.duration_seconds !== null || s.prompt_tokens !== null || s.llm_calls !== null;
  }

  /** Net of every lot traded on this signal. Null while any of them is
   * still open — a part-realized total reads as a finished result. */
  protected tradedPnl(s: SignalDetail): number | null {
    if (!s.agent_trades.length || s.agent_trades.some((t) => t.is_open)) return null;
    return s.agent_trades.reduce((sum, t) => sum + (t.pnl ?? 0), 0);
  }

  protected money(value: number | null): string {
    return value === null ? '—' : `$${value.toFixed(2)}`;
  }

  protected signed(value: number): string {
    return `${value >= 0 ? '+' : ''}$${value.toFixed(2)}`;
  }

  protected at(value: string | null): string {
    return value ? value.replace('T', ' ').slice(0, 16) : '—';
  }

  /** Sub-cent runs are the normal case for a self-hosted model, so two decimal
   * places would round every one of them to $0.00 and hide the comparison this
   * figure exists to make. */
  protected cost(usd: number | null): string {
    if (usd === null) return '—';
    return usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`;
  }

  protected costBasis(basis: string | null): string {
    return basis === 'vendor' ? 'estimated at list price' : 'GPU electricity';
  }

  protected duration(seconds: number): string {
    const whole = Math.round(seconds);
    const minutes = Math.floor(whole / 60);
    return minutes ? `${minutes}m ${whole % 60}s` : `${whole}s`;
  }

  /** How far the stop sits below the proposed entry, as a percentage — the
   * planned loss if the thesis fails. */
  protected stopDistance(s: SignalDetail): string {
    if (!s.entry_price || s.stop_loss === null) return '';
    return `${((s.stop_loss / s.entry_price - 1) * 100).toFixed(1)}%`;
  }
}
