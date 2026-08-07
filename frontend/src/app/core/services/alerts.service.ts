import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Alert } from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class AlertsService {
  private readonly http = inject(HttpClient);

  private readonly _alerts = signal<Alert[] | null>(null);
  readonly alerts = this._alerts.asReadonly();

  async load(alertType?: string): Promise<void> {
    const params: Record<string, string> = alertType ? { alert_type: alertType } : {};
    const data = await firstValueFrom(this.http.get<Alert[]>('/api/alerts', { params }));
    this._alerts.set(data);
  }
}
