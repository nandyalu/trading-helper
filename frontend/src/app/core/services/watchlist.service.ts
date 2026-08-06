import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { ActionResult } from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class WatchlistService {
  private readonly http = inject(HttpClient);

  private readonly _tickers = signal<string[]>([]);
  readonly tickers = this._tickers.asReadonly();

  async load(): Promise<void> {
    const data = await firstValueFrom(this.http.get<string[]>('/api/watchlist'));
    this._tickers.set(data);
  }

  async add(ticker: string): Promise<ActionResult> {
    const result = await firstValueFrom(
      this.http.post<ActionResult>(`/api/watchlist/${ticker}`, {})
    );
    await this.load();
    return result;
  }

  async remove(ticker: string): Promise<ActionResult> {
    const result = await firstValueFrom(this.http.delete<ActionResult>(`/api/watchlist/${ticker}`));
    await this.load();
    return result;
  }
}
