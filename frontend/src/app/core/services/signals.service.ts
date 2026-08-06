import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { ActionResult, Signal, SignalDetail } from '../models/api.models';

export interface SignalListParams {
  ticker?: string;
  status?: 'pending' | 'resolved';
  limit?: number;
}

@Injectable({ providedIn: 'root' })
export class SignalsService {
  private readonly http = inject(HttpClient);

  private readonly _signals = signal<Signal[]>([]);
  readonly signals = this._signals.asReadonly();

  async load(params: SignalListParams = {}): Promise<void> {
    const query: Record<string, string> = {};
    if (params.ticker) query['ticker'] = params.ticker;
    if (params.status) query['status'] = params.status;
    if (params.limit) query['limit'] = String(params.limit);
    const data = await firstValueFrom(this.http.get<Signal[]>('/api/signals', { params: query }));
    this._signals.set(data);
  }

  getDetail(id: number): Promise<SignalDetail> {
    return firstValueFrom(this.http.get<SignalDetail>(`/api/signals/${id}`));
  }

  follow(id: number): Promise<ActionResult> {
    return firstValueFrom(this.http.post<ActionResult>(`/api/signals/${id}/follow`, {}));
  }
}
