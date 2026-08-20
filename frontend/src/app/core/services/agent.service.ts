import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import {
  AgentBook,
  AgentComparison,
  AgentEquityPoint,
  AgentRun,
  AgentTrade,
  AgentTradeRow,
  UnprotectedPosition,
} from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class AgentService {
  private readonly http = inject(HttpClient);

  private readonly _book = signal<AgentBook | null>(null);
  private readonly _trades = signal<AgentTrade[]>([]);
  private readonly _performance = signal<AgentComparison | null>(null);
  private readonly _history = signal<AgentTradeRow[]>([]);
  private readonly _curve = signal<AgentEquityPoint[]>([]);
  private readonly _unprotected = signal<UnprotectedPosition[]>([]);
  readonly book = this._book.asReadonly();
  readonly trades = this._trades.asReadonly();
  readonly performance = this._performance.asReadonly();
  readonly history = this._history.asReadonly();
  readonly curve = this._curve.asReadonly();
  readonly unprotected = this._unprotected.asReadonly();

  /** Just the holdings with nothing resting under them. The Overview page
   * needs this without needing the whole book, and loading four other
   * endpoints to answer it would make the landing page wait on all of them. */
  async loadUnprotected(): Promise<void> {
    this._unprotected.set(
      await firstValueFrom(this.http.get<UnprotectedPosition[]>('/api/agent/unprotected')),
    );
  }

  async load(): Promise<void> {
    const [book, trades, performance, history, curve, unprotected] = await Promise.all([
      firstValueFrom(this.http.get<AgentBook>('/api/agent')),
      firstValueFrom(this.http.get<AgentTrade[]>('/api/agent/trades')),
      firstValueFrom(this.http.get<AgentComparison>('/api/agent/performance')),
      firstValueFrom(this.http.get<AgentTradeRow[]>('/api/agent/history')),
      firstValueFrom(this.http.get<AgentEquityPoint[]>('/api/agent/curve')),
      firstValueFrom(this.http.get<UnprotectedPosition[]>('/api/agent/unprotected')),
    ]);
    this._book.set(book);
    this._trades.set(trades);
    this._performance.set(performance);
    this._history.set(history);
    this._curve.set(curve);
    this._unprotected.set(unprotected);
  }

  async runNow(): Promise<AgentRun> {
    const run = await firstValueFrom(this.http.post<AgentRun>('/api/agent/run', {}));
    await this.load();
    return run;
  }
}
