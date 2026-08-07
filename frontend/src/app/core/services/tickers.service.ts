import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import {
  ActionResult,
  AnalyzeAllQueued,
  AnalyzeQueued,
  AskRequest,
  OhlcBar,
  TickerDetail,
  TickerEvents,
  TickerSummary,
} from '../models/api.models';

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

  /** Fetches a live quote and updates the price cache — for when the cached
   * price (kept warm by scheduled jobs) is too stale to act on. */
  refreshPrice(ticker: string): Promise<TickerDetail> {
    return firstValueFrom(this.http.post<TickerDetail>(`/api/tickers/${ticker}/refresh`, {}));
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

  analyze(ticker: string): Promise<AnalyzeQueued> {
    return firstValueFrom(this.http.post<AnalyzeQueued>(`/api/tickers/${ticker}/analyze`, {}));
  }

  analyzeAll(): Promise<AnalyzeAllQueued> {
    return firstValueFrom(this.http.post<AnalyzeAllQueued>('/api/tickers/analyze-all', {}));
  }

  ask(ticker: string, question: string): Promise<ActionResult> {
    const payload: AskRequest = { question };
    return firstValueFrom(this.http.post<ActionResult>(`/api/tickers/${ticker}/ask`, payload));
  }
}
