import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { ActionResult, PaperPortfolio, PaperSnapshot } from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class PaperService {
  private readonly http = inject(HttpClient);

  private readonly _portfolio = signal<PaperPortfolio | null>(null);
  private readonly _snapshots = signal<PaperSnapshot[]>([]);
  readonly portfolio = this._portfolio.asReadonly();
  readonly snapshots = this._snapshots.asReadonly();

  async load(): Promise<void> {
    const [portfolio, snapshots] = await Promise.all([
      firstValueFrom(this.http.get<PaperPortfolio>('/api/paper')),
      firstValueFrom(this.http.get<PaperSnapshot[]>('/api/paper/snapshots')),
    ]);
    this._portfolio.set(portfolio);
    this._snapshots.set(snapshots);
  }

  async close(ticker: string): Promise<ActionResult> {
    const result = await firstValueFrom(
      this.http.post<ActionResult>(`/api/paper/${ticker}/close`, {}),
    );
    await this.load();
    return result;
  }
}
