import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import {
  AgentBook,
  AgentComparison,
  AgentRun,
  AgentTrade,
  AgentTradeRow,
} from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class AgentService {
  private readonly http = inject(HttpClient);

  private readonly _book = signal<AgentBook | null>(null);
  private readonly _trades = signal<AgentTrade[]>([]);
  private readonly _performance = signal<AgentComparison | null>(null);
  private readonly _history = signal<AgentTradeRow[]>([]);
  readonly book = this._book.asReadonly();
  readonly trades = this._trades.asReadonly();
  readonly performance = this._performance.asReadonly();
  readonly history = this._history.asReadonly();

  async load(): Promise<void> {
    const [book, trades, performance, history] = await Promise.all([
      firstValueFrom(this.http.get<AgentBook>('/api/agent')),
      firstValueFrom(this.http.get<AgentTrade[]>('/api/agent/trades')),
      firstValueFrom(this.http.get<AgentComparison>('/api/agent/performance')),
      firstValueFrom(this.http.get<AgentTradeRow[]>('/api/agent/history')),
    ]);
    this._book.set(book);
    this._trades.set(trades);
    this._performance.set(performance);
    this._history.set(history);
  }

  async runNow(): Promise<AgentRun> {
    const run = await firstValueFrom(this.http.post<AgentRun>('/api/agent/run', {}));
    await this.load();
    return run;
  }
}
