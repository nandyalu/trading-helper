import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { Alert, PortfolioPosition, Signal, TickerSummary } from '../../core/models/api.models';
import { AlertsService } from '../../core/services/alerts.service';
import { PaperService } from '../../core/services/paper.service';
import { PortfolioService } from '../../core/services/portfolio.service';
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
 * Everything here already existed on some other page — positions on
 * /portfolio, alerts on /alerts, signals on /signals. What was missing was a
 * view that puts them together and sorts by urgency, so opening the app
 * answers "is there anything I should do?" rather than "here is a table".
 */
@Component({
  selector: 'app-overview',
  templateUrl: './overview.html',
  imports: [RouterLink, DecisionBadge],
})
export class Overview {
  private readonly alertsService = inject(AlertsService);
  private readonly portfolioService = inject(PortfolioService);
  private readonly paperService = inject(PaperService);
  private readonly regimeService = inject(RegimeService);
  private readonly scorecardService = inject(ScorecardService);
  private readonly signalsService = inject(SignalsService);
  private readonly tickersService = inject(TickersService);

  protected readonly regime = this.regimeService.regime;
  protected readonly portfolio = this.portfolioService.portfolio;
  protected readonly paper = this.paperService.portfolio;
  protected readonly scorecard = this.scorecardService.scorecard;
  protected readonly alerts = this.alertsService.alerts;
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

  /** Held positions, worst performer first — a losing position is the one
   * that needs a decision, so it goes at the top. */
  protected readonly positions = computed<PortfolioPosition[]>(() =>
    [...(this.portfolio()?.positions ?? [])].sort(
      (a, b) => (a.unrealized_pct ?? 0) - (b.unrealized_pct ?? 0),
    ),
  );

  /** Actionable signals from the last week that you are not already in: the
   * bot said buy, and you have no position. */
  protected readonly newOpportunities = computed(() => {
    const held = new Set(
      (this.portfolio()?.positions ?? [])
        .map((p) => p.ticker)
        .concat((this.paper()?.positions ?? []).map((p) => p.ticker)),
    );
    const cutoff = new Date(Date.now() - 7 * 86_400_000).toISOString().slice(0, 10);
    return this.signals().filter(
      (s) => BUYISH.has(s.decision) && !held.has(s.ticker) && s.signal_date >= cutoff,
    );
  });

  /** Held tickers whose newest signal says get out. */
  protected readonly exitSignals = computed(() => {
    const held = new Set((this.portfolio()?.positions ?? []).map((p) => p.ticker));
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
        this.portfolioService.load(),
        this.paperService.load(),
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
