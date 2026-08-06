import { Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { SignalDetail } from '../../core/models/api.models';
import { SignalsService } from '../../core/services/signals.service';
import { DecisionBadge } from '../../shared/decision-badge';

@Component({
  selector: 'app-signal-detail',
  imports: [RouterLink, DecisionBadge],
  templateUrl: './signal-detail.html',
})
export class SignalDetailPage {
  private readonly route = inject(ActivatedRoute);
  private readonly signalsService = inject(SignalsService);

  protected readonly signalDetail = signal<SignalDetail | null>(null);
  protected readonly following = signal(false);
  protected readonly message = signal<string | null>(null);

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.signalDetail.set(await this.signalsService.getDetail(id));
  }

  protected async follow(): Promise<void> {
    const current = this.signalDetail();
    if (!current) return;
    this.following.set(true);
    try {
      const result = await this.signalsService.follow(current.id);
      this.message.set(result.message);
    } finally {
      this.following.set(false);
    }
  }

  protected reportKeys(reports: Record<string, string>): string[] {
    return Object.keys(reports);
  }
}
