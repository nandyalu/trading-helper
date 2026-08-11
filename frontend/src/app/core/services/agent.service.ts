import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { AgentBook, AgentRun, AgentTrade } from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class AgentService {
  private readonly http = inject(HttpClient);

  private readonly _book = signal<AgentBook | null>(null);
  private readonly _trades = signal<AgentTrade[]>([]);
  readonly book = this._book.asReadonly();
  readonly trades = this._trades.asReadonly();

  async load(): Promise<void> {
    const [book, trades] = await Promise.all([
      firstValueFrom(this.http.get<AgentBook>('/api/agent')),
      firstValueFrom(this.http.get<AgentTrade[]>('/api/agent/trades')),
    ]);
    this._book.set(book);
    this._trades.set(trades);
  }

  async runNow(): Promise<AgentRun> {
    const run = await firstValueFrom(this.http.post<AgentRun>('/api/agent/run', {}));
    await this.load();
    return run;
  }
}
