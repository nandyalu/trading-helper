import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AlertsService } from '../../core/services/alerts.service';
import { alertIcon, alertLabel } from '../../shared/alert-types';

@Component({
  selector: 'app-alerts-view',
  templateUrl: './alerts-view.html',
  imports: [RouterLink],
})
export class AlertsView {
  private readonly alertsService = inject(AlertsService);
  protected readonly alerts = this.alertsService.alerts;

  protected readonly filter = signal<string>('');

  /** Types present in the current data, so the filter never offers an option
   * that would return nothing. */
  protected readonly availableTypes = computed(() => {
    const alerts = this.alerts() ?? [];
    return [...new Set(alerts.map((a) => a.alert_type))].sort();
  });

  protected readonly visible = computed(() => {
    const alerts = this.alerts() ?? [];
    const wanted = this.filter();
    return wanted ? alerts.filter((a) => a.alert_type === wanted) : alerts;
  });

  constructor() {
    void this.alertsService.load();
  }

  protected onFilterChange(e: Event): void {
    this.filter.set((e.target as HTMLSelectElement).value);
  }

  protected label = alertLabel;
  protected icon = alertIcon;

  protected when(iso: string): string {
    return new Date(iso).toLocaleString();
  }
}
