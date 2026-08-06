import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { TickersService } from '../../core/services/tickers.service';
import { WatchlistService } from '../../core/services/watchlist.service';
import { DecisionBadge } from '../../shared/decision-badge';

@Component({
  selector: 'app-ticker-list',
  imports: [RouterLink, DecisionBadge],
  templateUrl: './ticker-list.html',
})
export class TickerList implements OnInit {
  private readonly tickersService = inject(TickersService);
  private readonly watchlistService = inject(WatchlistService);

  protected readonly tickers = this.tickersService.tickers;
  protected readonly loading = this.tickersService.loading;
  protected readonly newTicker = signal('');
  protected readonly error = signal<string | null>(null);
  protected readonly analyzingAll = signal(false);
  protected readonly message = signal<string | null>(null);

  ngOnInit(): void {
    void this.tickersService.load();
  }

  protected async analyzeAll(): Promise<void> {
    this.analyzingAll.set(true);
    this.message.set(null);
    try {
      const result = await this.tickersService.analyzeAll();
      this.message.set(`Queued analysis for ${result.count} ticker(s) — check back shortly, or watch Discord.`);
    } catch {
      this.message.set("Couldn't queue analyze-all.");
    } finally {
      this.analyzingAll.set(false);
    }
  }

  protected onTickerInput(event: Event): void {
    this.newTicker.set((event.target as HTMLInputElement).value);
  }

  protected async addTicker(): Promise<void> {
    const ticker = this.newTicker().trim().toUpperCase();
    if (!ticker) return;
    this.error.set(null);
    try {
      await this.watchlistService.add(ticker);
      this.newTicker.set('');
      await this.tickersService.load();
    } catch {
      this.error.set(`Couldn't add ${ticker}.`);
    }
  }

  protected async removeTicker(ticker: string): Promise<void> {
    await this.watchlistService.remove(ticker);
    await this.tickersService.load();
  }
}
