import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Regime } from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class RegimeService {
  private readonly http = inject(HttpClient);

  private readonly _regime = signal<Regime | null>(null);
  readonly regime = this._regime.asReadonly();

  async load(): Promise<void> {
    const data = await firstValueFrom(this.http.get<Regime>('/api/regime'));
    this._regime.set(data);
  }
}
