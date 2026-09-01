import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { ActionResult, Settings, SettingsPatch } from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class SettingsService {
  private readonly http = inject(HttpClient);

  private readonly _settings = signal<Settings | null>(null);
  readonly settings = this._settings.asReadonly();

  async load(): Promise<void> {
    const data = await firstValueFrom(this.http.get<Settings>('/api/settings'));
    this._settings.set(data);
  }

  async update(patch: SettingsPatch): Promise<void> {
    const data = await firstValueFrom(this.http.patch<Settings>('/api/settings', patch));
    this._settings.set(data);
  }
}
