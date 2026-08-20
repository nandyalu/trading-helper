import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Calibration, Scorecard } from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class ScorecardService {
  private readonly http = inject(HttpClient);

  private readonly _scorecard = signal<Scorecard | null>(null);
  readonly scorecard = this._scorecard.asReadonly();

  private readonly _calibration = signal<Calibration | null>(null);
  readonly calibration = this._calibration.asReadonly();

  async load(ticker?: string): Promise<void> {
    const params: Record<string, string> = ticker ? { ticker } : {};
    // Calibration is not filtered by ticker: it is a property of the model,
    // and a handful of signals on one stock says nothing about it.
    const [data, calibration] = await Promise.all([
      firstValueFrom(this.http.get<Scorecard>('/api/scorecard', { params })),
      firstValueFrom(this.http.get<Calibration>('/api/scorecard/calibration')),
    ]);
    this._scorecard.set(data);
    this._calibration.set(calibration);
  }
}
