import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { OhlcBar, TickerDetail, TickerEvents, TickerSummary } from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class TickersService {
  private readonly http = inject(HttpClient);

  private readonly _tickers = signal<TickerSummary[]>([]);
  private readonly _loading = signal(false);

  readonly tickers = this._tickers.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly count = computed(() => this._tickers().length);

  async load(): Promise<void> {
    this._loading.set(true);
    try {
      const data = await firstValueFrom(this.http.get<TickerSummary[]>('/api/tickers'));
      this._tickers.set(data);
    } finally {
      this._loading.set(false);
    }
  }

  getDetail(ticker: string): Promise<TickerDetail> {
    return firstValueFrom(this.http.get<TickerDetail>(`/api/tickers/${ticker}`));
  }

  getChart(ticker: string, days = 90): Promise<OhlcBar[]> {
    return firstValueFrom(
      this.http.get<OhlcBar[]>(`/api/tickers/${ticker}/chart`, { params: { days } }),
    );
  }

  /** Bars, signals, alerts, and trades in one call — the chart overlays and
   * the timeline are the same events, so they must not be fetched separately
   * or they can disagree mid-flight. */
  getEvents(ticker: string, days = 180): Promise<TickerEvents> {
    return firstValueFrom(
      this.http.get<TickerEvents>(`/api/tickers/${ticker}/events`, { params: { days } }),
    );
  }
}
