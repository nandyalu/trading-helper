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
  private readonly route = inject(ActivatedRoute);
  private readonly signalsService = inject(SignalsService);

  protected readonly signalDetail = signal<SignalDetail | null>(null);
  protected readonly following = signal(false);
  protected readonly message = signal<string | null>(null);

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.signalDetail.set(await this.signalsService.getDetail(id));
  }

  protected async follow(): Promise<void> {
    const current = this.signalDetail();
    if (!current) return;
    this.following.set(true);
    try {
      const result = await this.signalsService.follow(current.id);
      this.message.set(result.message);
    } finally {
      this.following.set(false);
    }
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
