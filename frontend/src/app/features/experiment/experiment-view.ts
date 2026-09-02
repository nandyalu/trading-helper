import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AgentEvent, AgentHolding } from '../../core/models/api.models';
import { AgentService } from '../../core/services/agent.service';
import { RegimeService } from '../../core/services/regime.service';
import { ScorecardService } from '../../core/services/scorecard.service';
import { EquityChart, EquityPoint } from '../../shared/equity-chart';
import { Logo } from '../../shared/logo';
import { ClockTime, marketTime } from '../../shared/market-time';
import { dayNumber, startedOn } from '../../shared/experiment';

/** One row of the two-day timeline. */
interface Beat {
  t: ClockTime;
  text: string;
  done: boolean;
  act: boolean;
}

/**
 * The front door.
 *
 * Written for someone who has never heard of this. It gives the premise before
 * it gives a number, because a return of +2.4% means nothing until you know
 * what it is a return on and who chose the trades.
 *
 * The order is the design: what this is, what it may and may not do, that no
 * real money is involved, then the money, then what it did most recently in
 * its own words, then whether any of it is working.
 *
 * A visitor who stops after the first screen still leaves knowing what was
 * being tried. That is why the premise is prose and not a stat tile.
 */
@Component({
  selector: 'app-experiment-view',
  imports: [RouterLink, EquityChart, Logo],
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
  protected readonly failed = signal(false);

  protected readonly curvePoints = computed<EquityPoint[]>(() =>
    this.curve().map((p) => ({ time: p.date, value: p.equity })),
  );

  /** Biggest position first. Someone glancing at the table wants to know where
   * the money actually is, not which ticker sorts first. */
  protected readonly holdings = computed<AgentHolding[]>(() =>
    [...(this.book()?.holdings ?? [])].sort(
      (a, b) => (b.market_value ?? b.cost_basis) - (a.market_value ?? a.cost_basis),
    ),
  );

  /** Which day of the experiment this is, and the date it began.
   *
   * Counted from the start date rather than from the first fill. A day the
   * agent chose to do nothing is still a day of the experiment, and a counter
   * that waits for the first purchase hides exactly those days. */
  protected readonly dayNumber = dayNumber();
  protected readonly startedOn = startedOn();

  /** The most recent pass that did something.
   *
   * A quiet day is the common case, and leading with "it did nothing" three
   * days running says less about the experiment than the last real decision
   * does. The date on it keeps the gap visible either way. */
  protected readonly lastAction = computed<AgentEvent | null>(
    () => this.events().find((e) => e.orders.length > 0) ?? this.events()[0] ?? null,
  );

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

  /**
   * The day's schedule, with what has already run marked.
   *
   * The times are fixed and the app knows them; what varies is how far through
   * the day it is. `done` is decided against the wall clock in UTC, not the
   * reader's — a reader in Tokyo must not see tomorrow's pass marked complete
   * because it is already the next day where they are.
   */
  private beats(on: Date, now: Date): Beat[] {
    const rows: [number, number, string, boolean][] = [
      [11, 0, 'The morning sweep analyses the watchlist', false],
      [12, 45, 'The market regime is read', false],
      [13, 0, 'Anything reporting earnings gets a fresh look', false],
      [13, 35, 'It decides', true],
      [21, 30, 'Signals are graded, then the journal is written', false],
    ];
    return rows.map(([h, m, text, act]) => {
      const t = marketTime(h, m, on);
      return { t, text, act, done: t.instant.getTime() <= now.getTime() };
    });
  }

  private readonly now = new Date();

  protected readonly today = computed(() => this.beats(this.now, this.now));

  /** The previous weekday. Monday looks back to Friday: a timeline whose first
   * half is a closed market says nothing about the experiment. */
  protected readonly previous = computed(() => {
    const d = new Date(this.now);
    do {
      d.setUTCDate(d.getUTCDate() - 1);
    } while (d.getUTCDay() === 0 || d.getUTCDay() === 6);
    // Everything on a past day has happened, whatever the clock says now.
    return this.beats(d, new Date(8.64e15)).map((b) => ({ ...b, done: true }));
  });

  protected readonly previousLabel = computed(() => {
    const d = new Date(this.now);
    do {
      d.setUTCDate(d.getUTCDate() - 1);
    } while (d.getUTCDay() === 0 || d.getUTCDay() === 6);
    return new Intl.DateTimeFormat('en-US', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      timeZone: 'UTC',
    }).format(d);
  });

  protected readonly todayLabel = new Intl.DateTimeFormat('en-US', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    timeZone: 'UTC',
  }).format(this.now);

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      await Promise.all([
        this.agentService.load(),
        this.agentService.loadEvents(20),
        // Neither of these is allowed to fail the page. The regime is context
        // and the scorecard is a summary; the money above them still stands.
        this.regimeService.load().catch(() => {}),
        this.scorecardService.load().catch(() => {}),
      ]);
    } catch {
      this.failed.set(true);
    } finally {
      this.loading.set(false);
    }
  }

  protected clock(t: ClockTime): string {
    return `${t.time} ${t.zone}`;
  }

  protected signed(value: number, digits = 1): string {
    return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(digits)}`;
  }

  protected money(value: number, digits = 0): string {
    return value.toLocaleString('en-US', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  protected signedMoney(value: number): string {
    return `${value >= 0 ? '+$' : '−$'}${this.money(Math.abs(value), 2)}`;
  }

  protected pct(pnl: number | null, basis: number): string {
    if (pnl === null || !basis) return '—';
    return this.signed((pnl / basis) * 100) + '%';
  }

  protected when(iso: string): string {
    const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
    if (days === 0) return 'today';
    if (days === 1) return 'yesterday';
    return `${days} days ago`;
  }
}
