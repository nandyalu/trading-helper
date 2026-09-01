import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { Alert, AgentHolding, Signal, TickerSummary } from '../../core/models/api.models';
import { AgentService } from '../../core/services/agent.service';
import { AlertsService } from '../../core/services/alerts.service';
import { RegimeService } from '../../core/services/regime.service';
import { ScorecardService } from '../../core/services/scorecard.service';
import { SignalsService } from '../../core/services/signals.service';
import { TickersService } from '../../core/services/tickers.service';
import { DecisionBadge } from '../../shared/decision-badge';
import { ALERT_TYPES, alertIcon, alertLabel } from '../../shared/alert-types';

const BUYISH = new Set(['Buy', 'Overweight']);
const SELLISH = new Set(['Sell', 'Underweight']);

/** How recent an alert must be to count as "needs attention". Anything older
 * has either been acted on or stopped mattering. */
const ATTENTION_WINDOW_DAYS = 3;

/**
 * The landing page: what is going on right now, and what needs a decision.
 *
 * Everything here already existed on some other page — holdings on /agent,
 * alerts on /alerts, signals on /signals. What was missing was a view that
 * puts them together and sorts by urgency, so opening the app answers "what is
 * the agent doing, and is anything wrong?" rather than "here is a table".
 */
@Component({
  selector: 'app-overview',
  templateUrl: './overview.html',
  imports: [RouterLink, DecisionBadge],
})
export class Overview {
  private readonly agentService = inject(AgentService);
  private readonly alertsService = inject(AlertsService);
  private readonly regimeService = inject(RegimeService);
  private readonly scorecardService = inject(ScorecardService);
  private readonly signalsService = inject(SignalsService);
  private readonly tickersService = inject(TickersService);

  protected readonly regime = this.regimeService.regime;
  protected readonly book = this.agentService.book;
  protected readonly scorecard = this.scorecardService.scorecard;
  protected readonly alerts = this.alertsService.alerts;

  /** Auto-trader holdings with nothing resting at the broker to close them.
   * This belongs above everything else on the page: the money is at risk now,
   * and the exit everyone assumes is there is not. */
  protected readonly unprotected = this.agentService.unprotected;
  protected readonly tickers = this.tickersService.tickers;

  protected readonly signals = signal<Signal[]>([]);
  protected readonly loading = signal(true);

  protected readonly label = alertLabel;
  protected readonly icon = alertIcon;

  /** Recent alerts of a type that implies a decision — a breached stop or a
   * reached target. A big move or a volume spike is information, not a
   * prompt, so it stays off this list and on /alerts. */
  protected readonly needsAttention = computed(() => {
    const cutoff = Date.now() - ATTENTION_WINDOW_DAYS * 86_400_000;
    return (this.alerts() ?? []).filter(
      (a) => ALERT_TYPES[a.alert_type]?.urgent && new Date(a.created_at).getTime() >= cutoff,
    );
  });

  /** What the agent holds, worst performer first — a losing position is the
   * one worth looking at, so it goes at the top. */
  protected readonly positions = computed<AgentHolding[]>(() =>
    [...(this.book()?.holdings ?? [])].sort(
      (a, b) => this.unrealizedPct(a) - this.unrealizedPct(b),
    ),
  );

  /** Buy-ish signals from the last week the agent has not acted on. Not a
   * to-do list — nobody here places a trade. It says what the analyses found
   * and the agent left alone, which is half of reading how it behaves. */
  protected readonly newOpportunities = computed(() => {
    const held = new Set((this.book()?.holdings ?? []).map((h) => h.ticker));
    const cutoff = new Date(Date.now() - 7 * 86_400_000).toISOString().slice(0, 10);
    return this.signals().filter(
      (s) => BUYISH.has(s.decision) && !held.has(s.ticker) && s.signal_date >= cutoff,
    );
  });

  /** Held tickers whose newest signal says get out. */
  protected readonly exitSignals = computed(() => {
    const held = new Set((this.book()?.holdings ?? []).map((h) => h.ticker));
    const seen = new Set<string>();
    return this.signals().filter((s) => {
      if (!held.has(s.ticker) || seen.has(s.ticker)) return false;
      seen.add(s.ticker);
      return SELLISH.has(s.decision);
    });
  });

  protected readonly staleTickers = computed(() => this.tickers().filter((t) => !t.latest_signal));

  protected readonly winRate = computed(() => {
    const s = this.scorecard();
    if (!s || s.resolved === 0) return null;
    return { passes: s.passes, total: s.resolved, pct: Math.round((s.passes / s.resolved) * 100) };
  });

  /** Below this many resolved signals a win rate is noise, not evidence.
   * Three wins in four reads as 75% and means nothing. */
  protected readonly enoughData = computed(() => (this.scorecard()?.resolved ?? 0) >= 20);

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      await Promise.all([
        this.regimeService.load(),
        this.agentService.load(),
        this.scorecardService.load(),
        this.alertsService.load(),
        this.tickersService.load(),
        this.signalsService
          .load({ limit: 40 })
          .then(() => this.signals.set(this.signalsService.signals())),
      ]);
    } finally {
      this.loading.set(false);
    }
  }

  protected when(iso: string): string {
    const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
    if (days === 0) return 'today';
    if (days === 1) return 'yesterday';
    return `${days}d ago`;
  }

  /** Percent gain or loss on a holding. AgentHolding carries the dollar
   * figure and the cost basis but not the ratio, and a zero basis would divide
   * by nothing. */
  protected unrealizedPct(holding: AgentHolding): number {
    if (!holding.cost_basis || holding.unrealized_pnl === null) return 0;
    return (holding.unrealized_pnl / holding.cost_basis) * 100;
  }

  protected signed(value: number, digits = 1): string {
    return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`;
  }

  protected trackAlert(_i: number, alert: Alert): number {
    return alert.id;
  }

  protected trackTicker(_i: number, ticker: TickerSummary): string {
    return ticker.ticker;
  }
}
