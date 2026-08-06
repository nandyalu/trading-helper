import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Scorecard } from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class ScorecardService {
  private readonly http = inject(HttpClient);

  private readonly _scorecard = signal<Scorecard | null>(null);
  readonly scorecard = this._scorecard.asReadonly();

  async load(ticker?: string): Promise<void> {
    const params: Record<string, string> = ticker ? { ticker } : {};
    const data = await firstValueFrom(this.http.get<Scorecard>('/api/scorecard', { params }));
    this._scorecard.set(data);
  }
}
