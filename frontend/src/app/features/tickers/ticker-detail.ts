import { Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { Signal, TickerDetail, TickerEvents } from '../../core/models/api.models';
import { TickersService } from '../../core/services/tickers.service';
import { TransactionsService } from '../../core/services/transactions.service';
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
  private readonly tickersService = inject(TickersService);
  private readonly watchlistService = inject(WatchlistService);
  private readonly transactionsService = inject(TransactionsService);

  protected readonly ticker = signal(this.route.snapshot.paramMap.get('ticker') ?? '');
  protected readonly detail = signal<TickerDetail | null>(null);
  protected readonly events = signal<TickerEvents | null>(null);
  protected readonly analyzing = signal(false);
  protected readonly message = signal<string | null>(null);
  protected readonly refreshingPrice = signal(false);
  // 30 days, matching the 1-2 week trade horizon: the window a signal is
  // actually judged over, rather than six months of context around it.
  protected readonly chartDays = signal(30);

  protected readonly tradePrice = signal(0);
  protected readonly tradeQuantity = signal(0);
  protected readonly trading = signal(false);
  protected readonly tradeMessage = signal<string | null>(null);

  protected readonly question = signal('');
  protected readonly asking = signal(false);
  protected readonly answer = signal<string | null>(null);

  protected readonly signals = computed(() => this.events()?.signals ?? []);
  protected readonly alerts = computed(() => this.events()?.alerts ?? []);
  protected readonly trades = computed(() => this.events()?.trades ?? []);
  protected readonly bars = computed(() => this.events()?.bars ?? []);

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
        icon: t.book === 'paper' ? '📄' : '💵',
        title: `${t.book === 'paper' ? 'Paper ' : ''}${t.side === 'buy' ? 'buy' : 'sell'}`,
        detail: `${t.quantity} @ $${t.price.toFixed(2)}`,
      });
    }

    return entries.sort((a, b) => b.date.localeCompare(a.date));
  });

  constructor() {
    void this.refresh();
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

  protected async refreshPrice(): Promise<void> {
    this.refreshingPrice.set(true);
    try {
      this.detail.set(await this.tickersService.refreshPrice(this.ticker()));
    } catch {
      this.message.set("Couldn't fetch a live price.");
    } finally {
      this.refreshingPrice.set(false);
    }
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

  protected async analyze(): Promise<void> {
    this.analyzing.set(true);
    this.message.set(null);
    try {
      await this.tickersService.analyze(this.ticker());
      this.message.set(
        'Analysis queued. It takes a few minutes — reload this page to see the new signal.',
      );
    } catch {
      this.message.set("Couldn't queue analysis.");
    } finally {
      this.analyzing.set(false);
    }
  }

  protected async untrack(): Promise<void> {
    await this.watchlistService.remove(this.ticker());
  }

  protected onTradePriceInput(e: Event): void {
    this.tradePrice.set(Number((e.target as HTMLInputElement).value));
  }

  protected onTradeQuantityInput(e: Event): void {
    this.tradeQuantity.set(Number((e.target as HTMLInputElement).value));
  }

  protected async trade(side: 'buy' | 'sell'): Promise<void> {
    const payload = {
      ticker: this.ticker(),
      price: this.tradePrice(),
      quantity: this.tradeQuantity(),
    };
    if (!payload.price || !payload.quantity) return;
    this.trading.set(true);
    this.tradeMessage.set(null);
    try {
      const result =
        side === 'buy'
          ? await this.transactionsService.buy(payload)
          : await this.transactionsService.sell(payload);
      this.tradeMessage.set(result.message);
      await this.refresh();
    } catch (err) {
      const detail = (err as { error?: { detail?: string } })?.error?.detail;
      this.tradeMessage.set(detail ?? `Couldn't ${side}.`);
    } finally {
      this.trading.set(false);
    }
  }

  protected onQuestionInput(e: Event): void {
    this.question.set((e.target as HTMLInputElement).value);
  }

  protected async ask(): Promise<void> {
    const question = this.question().trim();
    if (!question) return;
    this.asking.set(true);
    this.answer.set(null);
    try {
      const result = await this.tickersService.ask(this.ticker(), question);
      this.answer.set(result.message);
    } catch {
      this.answer.set("Couldn't get an answer.");
    } finally {
      this.asking.set(false);
    }
  }

  protected signed(value: number, digits = 1): string {
    return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`;
  }

  protected trackTimeline(_index: number, entry: TimelineEntry): string {
    return `${entry.kind}:${entry.date}:${entry.title}:${entry.detail}`;
  }
}
