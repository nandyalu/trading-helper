import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { ActionResult, Candidate } from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class WatchlistService {
  private readonly http = inject(HttpClient);

  private readonly _tickers = signal<string[]>([]);
  private readonly _candidates = signal<Candidate[]>([]);
  readonly tickers = this._tickers.asReadonly();
  readonly candidates = this._candidates.asReadonly();

  async load(): Promise<void> {
    const data = await firstValueFrom(this.http.get<string[]>('/api/watchlist'));
    this._tickers.set(data);
  }

  /** Screened suggestions. Loaded separately from the watchlist because it
   * calls out to the broker's screener and is slower — the page should not
   * wait on it to show what you already follow. */
  async loadCandidates(): Promise<void> {
    const data = await firstValueFrom(this.http.get<Candidate[]>('/api/watchlist/candidates'));
    this._candidates.set(data);
  }

  async add(ticker: string): Promise<ActionResult> {
    const result = await firstValueFrom(
      this.http.post<ActionResult>(`/api/watchlist/${ticker}`, {}),
    );
    await this.load();
    // Drop it from the suggestions rather than refetching the screen: it is
    // now tracked, so the next screen would exclude it anyway.
    this._candidates.update((list) => list.filter((c) => c.ticker !== ticker.toUpperCase()));
    return result;
  }

  async remove(ticker: string): Promise<ActionResult> {
    const result = await firstValueFrom(this.http.delete<ActionResult>(`/api/watchlist/${ticker}`));
    await this.load();
    return result;
  }
}
