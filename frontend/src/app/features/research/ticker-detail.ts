import { Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { Lot, Signal, TickerDetail, TickerEvents } from '../../core/models/api.models';
import { AgentService } from '../../core/services/agent.service';
import { SettingsService } from '../../core/services/settings.service';
import { TickersService } from '../../core/services/tickers.service';
import { WatchlistService } from '../../core/services/watchlist.service';
import { DecisionBadge } from '../../shared/decision-badge';
import { PriceChart } from '../../shared/price-chart';
import { ALERT_TYPES } from '../../shared/alert-types';

/** One row in the merged history: a signal, an alert, or a trade, all reduced
 * to what a timeline needs. The three come from different tables and carry
 * different fields, so the page flattens them rather than rendering three
 * lists the reader has to interleave by eye. */
interface TimelineEntry {
  date: string;
  kind: 'signal' | 'alert' | 'trade';
  icon: string;
  title: string;
  detail: string;
  link?: (string | number)[];
  outcome?: 'pass' | 'fail' | null;
}

@Component({
  selector: 'app-ticker-detail',
  imports: [RouterLink, DecisionBadge, PriceChart],
  templateUrl: './ticker-detail.html',
})
export class TickerDetailPage {
  private readonly route = inject(ActivatedRoute);
  private readonly agentService = inject(AgentService);
  private readonly settingsService = inject(SettingsService);
  private readonly tickersService = inject(TickersService);
  private readonly watchlistService = inject(WatchlistService);

  protected readonly ticker = signal(this.route.snapshot.paramMap.get('ticker') ?? '');
  protected readonly detail = signal<TickerDetail | null>(null);
  protected readonly events = signal<TickerEvents | null>(null);
  /** True on the published copy. Hides the arm-exits button, which is the one
   * write this app still has. The backend refuses it either way — this removes
   * a control that would only ever return 403. */
  protected readonly isPublic = signal(false);
  protected readonly arming = signal(false);
  protected readonly armMessage = signal<string | null>(null);
  // 30 days, matching the 1-2 week trade horizon: the window a signal is
  // actually judged over, rather than six months of context around it.
  protected readonly chartDays = signal(30);

  protected readonly signals = computed(() => this.events()?.signals ?? []);
  protected readonly alerts = computed(() => this.events()?.alerts ?? []);
  protected readonly trades = computed(() => this.events()?.trades ?? []);
  protected readonly bars = computed(() => this.events()?.bars ?? []);
  protected readonly lots = computed(() => this.events()?.lots ?? []);

  /** The auto trader's position, if it holds any. Kept apart from the real and
   * paper ones because it is the only book with orders resting at a broker. */
  protected readonly agentPosition = computed(() => this.detail()?.agent_position ?? null);

  /** The stop and target the broker will actually execute — not the signal's.
   * The two disagree often: a discarded level, an ATR-derived fallback, or a
   * bracket the broker refused. Showing the signal's where these belong is how
   * an unprotected position looks protected. */
  protected readonly restingStop = computed(
    () => this.agentPosition()?.exits.find((e) => e.kind === 'stop')?.price ?? null,
  );
  protected readonly restingTarget = computed(
    () => this.agentPosition()?.exits.find((e) => e.kind === 'target')?.price ?? null,
  );

  /** The signal whose levels are still in force — the newest one. Its stop and
   * target are what the chart draws, because an older signal's levels were
   * superseded, not merely graded. */
  protected readonly activeSignal = computed<Signal | null>(() => this.signals()[0] ?? null);

  protected readonly stopLevel = computed(() => this.activeSignal()?.stop_loss ?? null);
  protected readonly targetLevel = computed(() => this.activeSignal()?.price_target ?? null);

  /** Distance from the current price to the stop, as a percentage. This is the
   * planned loss from here — the number worth seeing before the alert fires
   * rather than after. */
  protected readonly stopDistancePct = computed(() => {
    const price = this.detail()?.current_price;
    const stop = this.stopLevel();
    if (!price || stop === null) return null;
    return (stop / price - 1) * 100;
  });

  protected readonly targetDistancePct = computed(() => {
    const price = this.detail()?.current_price;
    const target = this.targetLevel();
    if (!price || target === null) return null;
    return (target / price - 1) * 100;
  });

  /** A level the price has already crossed is not "N% away" — that phrasing
   * reads as though there were still room, when in fact the decision is due
   * now. Say it plainly instead. */
  protected readonly stopStatus = computed(() => {
    const distance = this.stopDistancePct();
    if (distance === null) return null;
    return distance >= 0 ? 'breached' : `${Math.abs(distance).toFixed(1)}% below`;
  });

  protected readonly targetStatus = computed(() => {
    const distance = this.targetDistancePct();
    if (distance === null) return null;
    return distance <= 0 ? 'reached' : `${distance.toFixed(1)}% above`;
  });

  protected readonly stopBreached = computed(() => (this.stopDistancePct() ?? -1) >= 0);
  protected readonly targetReached = computed(() => (this.targetDistancePct() ?? 1) <= 0);

  protected readonly timeline = computed<TimelineEntry[]>(() => {
    const entries: TimelineEntry[] = [];

    for (const s of this.signals()) {
      entries.push({
        date: s.signal_date,
        kind: 'signal',
        icon: '🧠',
        title: `${s.decision} signal`,
        detail: this.signalDetail(s),
        link: ['/signals', s.id],
        outcome: s.outcome,
      });
    }
    for (const a of this.alerts()) {
      entries.push({
        date: a.created_at.slice(0, 10),
        kind: 'alert',
        icon: ALERT_TYPES[a.alert_type]?.icon ?? '•',
        title: ALERT_TYPES[a.alert_type]?.label ?? a.alert_type,
        detail: a.message,
      });
    }
    for (const t of this.trades()) {
      entries.push({
        date: t.date,
        kind: 'trade',
        icon: '💵',
        title: t.side === 'buy' ? 'buy' : 'sell',
        detail: `${t.quantity} @ $${t.price.toFixed(2)}`,
      });
    }

    return entries.sort((a, b) => b.date.localeCompare(a.date));
  });

  constructor() {
    void this.refresh();
    void this.settingsService
      .load()
      .then(() => this.isPublic.set(this.settingsService.settings()?.public ?? false))
      .catch(() => this.isPublic.set(false));
  }

  private signalDetail(s: Signal): string {
    const parts = [`entered at $${s.price_at_signal.toFixed(2)}`];
    if (s.stop_loss !== null) parts.push(`stop $${s.stop_loss.toFixed(2)}`);
    if (s.price_target !== null) parts.push(`target $${s.price_target.toFixed(2)}`);
    if (s.win_probability !== null) parts.push(`${s.win_probability.toFixed(0)}% confidence`);
    return parts.join(' · ');
  }

  private async refresh(): Promise<void> {
    const ticker = this.ticker();
    const [detail, events] = await Promise.all([
      this.tickersService.getDetail(ticker),
      this.tickersService.getEvents(ticker, this.chartDays()),
    ]);
    this.detail.set(detail);
    this.events.set(events);
  }

  protected async setChartDays(days: number): Promise<void> {
    this.chartDays.set(days);
    this.events.set(await this.tickersService.getEvents(this.ticker(), days));
  }

  protected priceAge(updatedAt: string | null): string {
    if (!updatedAt) return 'never fetched';
    const minutes = Math.round((Date.now() - new Date(updatedAt).getTime()) / 60_000);
    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.round(hours / 24)}d ago`;
  }

  protected signed(value: number, digits = 1): string {
    return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`;
  }

  /** Rest the missing exits under a position the auto trader already holds.
   * The remediation for a bracket the broker refused — which used to need a
   * Python shell, while the position sat exposed. */
  protected async armExits(): Promise<void> {
    this.arming.set(true);
    this.armMessage.set(null);
    try {
      const result = await this.agentService.armExits(this.ticker());
      this.armMessage.set(result.message);
      await this.refresh();
    } catch (err) {
      const detail = (err as { error?: { detail?: string } })?.error?.detail;
      this.armMessage.set(detail ?? "Couldn't place the exits.");
    } finally {
      this.arming.set(false);
    }
  }

  protected trackLot(_index: number, lot: Lot): string {
    return `${lot.entry_at}:${lot.entry}:${lot.quantity}:${lot.exit_at ?? ''}`;
  }

  protected trackTimeline(_index: number, entry: TimelineEntry): string {
    return `${entry.kind}:${entry.date}:${entry.title}:${entry.detail}`;
  }
}
