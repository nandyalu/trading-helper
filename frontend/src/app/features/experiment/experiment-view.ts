import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AgentEvent, AgentHolding } from '../../core/models/api.models';
import { AgentService } from '../../core/services/agent.service';
import { RegimeService } from '../../core/services/regime.service';
import { ScorecardService } from '../../core/services/scorecard.service';
import { LineChart, LineChartPoint } from '../../shared/line-chart';

/**
 * The front door.
 *
 * This page is for someone who has never heard of the experiment. It gives the
 * premise before it gives a number, because a return of +2.4% means nothing
 * until you know what it is a return on and who chose the trades.
 *
 * The order is deliberate and is the whole design:
 *
 * 1. What this is, in a sentence anyone can finish reading.
 * 2. That nobody can nudge it — the claim the rest of the page rests on.
 * 3. The money: equity against the $10,000, and the curve.
 * 4. What it did most recently, in its own words.
 * 5. Where to read more.
 *
 * A visitor who stops after the first screen should still leave knowing what
 * was being tried. That is why the premise is text and not a stat tile.
 */
@Component({
  selector: 'app-experiment-view',
  imports: [RouterLink, LineChart],
  templateUrl: './experiment-view.html',
})
export class ExperimentView {
  private readonly agentService = inject(AgentService);
  private readonly regimeService = inject(RegimeService);
  private readonly scorecardService = inject(ScorecardService);

  protected readonly book = this.agentService.book;
  protected readonly curve = this.agentService.curve;
  protected readonly regime = this.regimeService.regime;
  protected readonly scorecard = this.scorecardService.scorecard;
  protected readonly events = this.agentService.events;

  protected readonly loading = signal(true);

  /** The most recent pass that actually did something.
   *
   * A quiet day is the common case, and leading the page with "it did nothing"
   * three days running would say less about the experiment than the last real
   * decision does. The date on it makes the gap visible either way. */
  protected readonly lastAction = computed<AgentEvent | null>(
    () => this.events().find((e) => e.orders.length > 0) ?? this.events()[0] ?? null,
  );

  /** Days since the experiment's first equity point. The curve starts at the
   * first fill, so this counts days of actual trading rather than days since
   * the container came up. */
  protected readonly daysRunning = computed(() => {
    const first = this.curve()[0];
    if (!first) return 0;
    return Math.max(1, Math.round((Date.now() - new Date(first.date).getTime()) / 86_400_000));
  });

  /** The equity curve, as the chart wants it. Budget is not drawn as a second
   * series: the chart's own baseline does that job, and a flat line labelled
   * "$10,000" across a chart that starts at $10,000 adds ink and no fact. */
  protected readonly curvePoints = computed<LineChartPoint[]>(() =>
    this.curve().map((p) => ({ time: p.date, value: p.equity })),
  );

  protected readonly holdings = computed<AgentHolding[]>(() =>
    [...(this.book()?.holdings ?? [])].sort(
      (a, b) => (b.market_value ?? 0) - (a.market_value ?? 0),
    ),
  );

  /** Signals graded so far, and how many beat SPY. Below about twenty resolved
   * this is noise, and the template says so rather than printing a percentage
   * that reads as a finding. */
  protected readonly graded = computed(() => {
    const s = this.scorecard();
    if (!s || s.resolved === 0) return null;
    return {
      resolved: s.resolved,
      passes: s.passes,
      vsBenchmark: s.vs_benchmark_passes,
      vsBenchmarkTotal: s.vs_benchmark_total,
      enough: s.resolved >= 20,
    };
  });

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      await Promise.all([
        this.agentService.load(),
        this.agentService.loadEvents(20),
        this.regimeService.load(),
        this.scorecardService.load(),
      ]);
    } finally {
      this.loading.set(false);
    }
  }

  protected signed(value: number, digits = 1): string {
    return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`;
  }

  protected money(value: number): string {
    return value.toLocaleString('en-US', { maximumFractionDigits: 0 });
  }

  protected when(iso: string): string {
    const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
    if (days === 0) return 'today';
    if (days === 1) return 'yesterday';
    return `${days} days ago`;
  }
}
