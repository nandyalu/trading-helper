import { Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { OhlcBar, Signal, TickerDetail } from '../../core/models/api.models';
import { SignalsService } from '../../core/services/signals.service';
import { TickersService } from '../../core/services/tickers.service';
import { TransactionsService } from '../../core/services/transactions.service';
import { WatchlistService } from '../../core/services/watchlist.service';
import { DecisionBadge } from '../../shared/decision-badge';
import { PriceChart } from '../../shared/price-chart';

@Component({
  selector: 'app-ticker-detail',
  imports: [RouterLink, DecisionBadge, PriceChart],
  templateUrl: './ticker-detail.html',
})
export class TickerDetailPage {
  private readonly route = inject(ActivatedRoute);
  private readonly tickersService = inject(TickersService);
  private readonly signalsService = inject(SignalsService);
  private readonly watchlistService = inject(WatchlistService);
  private readonly transactionsService = inject(TransactionsService);

  protected readonly ticker = signal(this.route.snapshot.paramMap.get('ticker') ?? '');
  protected readonly detail = signal<TickerDetail | null>(null);
  protected readonly bars = signal<OhlcBar[]>([]);
  protected readonly signals = signal<Signal[]>([]);
  protected readonly analyzing = signal(false);
  protected readonly message = signal<string | null>(null);

  protected readonly tradePrice = signal(0);
  protected readonly tradeQuantity = signal(0);
  protected readonly trading = signal(false);
  protected readonly tradeMessage = signal<string | null>(null);

  protected readonly question = signal('');
  protected readonly asking = signal(false);
  protected readonly answer = signal<string | null>(null);

  constructor() {
    void this.refresh();
  }

  private async refresh(): Promise<void> {
    const ticker = this.ticker();
    const [detail, bars] = await Promise.all([
      this.tickersService.getDetail(ticker),
      this.tickersService.getChart(ticker),
      this.signalsService.load({ ticker, limit: 10 }),
    ]);
    this.detail.set(detail);
    this.bars.set(bars);
    this.signals.set(this.signalsService.signals());
  }

  protected async analyze(): Promise<void> {
    this.analyzing.set(true);
    this.message.set(null);
    try {
      await this.tickersService.analyze(this.ticker());
      this.message.set('Analysis queued — check back shortly, or watch Discord.');
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
    const payload = { ticker: this.ticker(), price: this.tradePrice(), quantity: this.tradeQuantity() };
    if (!payload.price || !payload.quantity) return;
    this.trading.set(true);
    this.tradeMessage.set(null);
    try {
      const result = side === 'buy' ? await this.transactionsService.buy(payload) : await this.transactionsService.sell(payload);
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
}
