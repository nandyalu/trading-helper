import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { SignalsService } from '../../core/services/signals.service';
import { DecisionBadge } from '../../shared/decision-badge';

type StatusFilter = '' | 'pending' | 'resolved';

@Component({
  selector: 'app-signal-list',
  imports: [RouterLink, DecisionBadge],
  templateUrl: './signal-list.html',
})
export class SignalList {
  private readonly signalsService = inject(SignalsService);

  protected readonly signals = this.signalsService.signals;
  protected readonly statusFilter = signal<StatusFilter>('');

  constructor() {
    void this.reload();
  }

  protected async setFilter(status: StatusFilter): Promise<void> {
    this.statusFilter.set(status);
    await this.reload();
  }

  private async reload(): Promise<void> {
    const status = this.statusFilter();
    await this.signalsService.load({ status: status || undefined, limit: 50 });
  }
}
