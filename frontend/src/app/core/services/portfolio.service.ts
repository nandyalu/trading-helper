import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Portfolio } from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class PortfolioService {
  private readonly http = inject(HttpClient);

  private readonly _portfolio = signal<Portfolio | null>(null);
  readonly portfolio = this._portfolio.asReadonly();

  async load(): Promise<void> {
    const data = await firstValueFrom(this.http.get<Portfolio>('/api/portfolio'));
    this._portfolio.set(data);
  }
}
