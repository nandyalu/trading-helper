import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Digest } from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class DigestService {
  private readonly http = inject(HttpClient);

  private readonly _digest = signal<Digest | null>(null);
  readonly digest = this._digest.asReadonly();

  async load(): Promise<void> {
    const data = await firstValueFrom(this.http.get<Digest>('/api/digest'));
    this._digest.set(data);
  }
}
