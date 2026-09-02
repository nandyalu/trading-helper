import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import {
  AgentBook,
  AgentComparison,
  AgentEquityPoint,
  AgentTrade,
  AgentTradeRow,
  ActionResult,
  UnprotectedPosition,
  AgentEvent,
  JourneyEntry,
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
  private readonly _events = signal<AgentEvent[]>([]);
  private readonly _journey = signal<JourneyEntry[]>([]);
  readonly book = this._book.asReadonly();
  readonly trades = this._trades.asReadonly();
  readonly performance = this._performance.asReadonly();
  readonly history = this._history.asReadonly();
  readonly curve = this._curve.asReadonly();
  readonly unprotected = this._unprotected.asReadonly();
  readonly events = this._events.asReadonly();
  readonly journey = this._journey.asReadonly();

  /** Place the missing exits on a position the agent already holds. Rests a
   * stop and a take-profit under shares that are already owned, which is the
   * one action that can only reduce exposure — it opens nothing. */
  async armExits(ticker: string): Promise<ActionResult> {
    return firstValueFrom(this.http.post<ActionResult>(`/api/agent/exits/${ticker}`, {}));
  }

  /** Just the holdings with nothing resting under them. The Overview page
   * needs this without needing the whole book, and loading four other
   * endpoints to answer it would make the landing page wait on all of them. */
  async loadUnprotected(): Promise<void> {
    this._unprotected.set(
      await firstValueFrom(this.http.get<UnprotectedPosition[]>('/api/agent/unprotected')),
    );
  }

  /** Decision passes with their prompts. Its own call, not part of load():
   * a prompt is tens of kilobytes and only the Decisions page shows one. */
  async loadEvents(limit = 30): Promise<void> {
    this._events.set(
      await firstValueFrom(this.http.get<AgentEvent[]>(`/api/agent/events?limit=${limit}`)),
    );
  }

  async loadJourney(days = 10): Promise<void> {
    this._journey.set(
      await firstValueFrom(
        this.http.get<JourneyEntry[]>(`/api/agent/journey/entries?days=${days}`),
      ),
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
}
