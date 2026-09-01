import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Candidate } from '../models/api.models';

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

  /** The screened names the agent may commission. Read-only: only the agent
   * adds a ticker, by paying for research on it.
   *
   * Loaded separately from the watchlist because it calls the screener and is
   * slower — the page should not wait on it to show what is already tracked. */
  async loadCandidates(): Promise<void> {
    const data = await firstValueFrom(this.http.get<Candidate[]>('/api/watchlist/candidates'));
    this._candidates.set(data);
  }
}
