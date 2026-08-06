import { Component, effect, inject, signal } from '@angular/core';

import { SettingsService } from '../../core/services/settings.service';

@Component({
  selector: 'app-settings-view',
  templateUrl: './settings-view.html',
})
export class SettingsView {
  private readonly settingsService = inject(SettingsService);
  protected readonly settings = this.settingsService.settings;

  protected readonly paperNotional = signal(1000);
  protected readonly riskEquity = signal<number | null>(null);
  protected readonly riskPct = signal(1);
  protected readonly alertMovePct = signal(5);
  protected readonly alertStopPct = signal(10);
  protected readonly alertVolumeMult = signal(2);
  protected readonly alertsEnabled = signal(true);
  protected readonly dailySweepEnabled = signal(true);

  protected readonly saving = signal(false);
  protected readonly message = signal<string | null>(null);
  protected readonly syncing = signal(false);

  constructor() {
    effect(() => {
      const s = this.settings();
      if (!s) return;
      this.paperNotional.set(s.paper_notional);
      this.riskEquity.set(s.risk_equity);
      this.riskPct.set(s.risk_pct);
      this.alertMovePct.set(s.alert_move_pct);
      this.alertStopPct.set(s.alert_stop_pct);
      this.alertVolumeMult.set(s.alert_volume_mult);
      this.alertsEnabled.set(s.alerts_enabled);
      this.dailySweepEnabled.set(s.daily_sweep_enabled);
    });
    void this.settingsService.load();
  }

  protected onPaperNotionalInput(e: Event): void {
    this.paperNotional.set(Number((e.target as HTMLInputElement).value));
  }

  protected onRiskEquityInput(e: Event): void {
    const value = (e.target as HTMLInputElement).value;
    this.riskEquity.set(value === '' ? null : Number(value));
  }

  protected onRiskPctInput(e: Event): void {
    this.riskPct.set(Number((e.target as HTMLInputElement).value));
  }

  protected onAlertMovePctInput(e: Event): void {
    this.alertMovePct.set(Number((e.target as HTMLInputElement).value));
  }

  protected onAlertStopPctInput(e: Event): void {
    this.alertStopPct.set(Number((e.target as HTMLInputElement).value));
  }

  protected onAlertVolumeMultInput(e: Event): void {
    this.alertVolumeMult.set(Number((e.target as HTMLInputElement).value));
  }

  protected onAlertsEnabledChange(e: Event): void {
    this.alertsEnabled.set((e.target as HTMLInputElement).checked);
  }

  protected onDailySweepChange(e: Event): void {
    this.dailySweepEnabled.set((e.target as HTMLInputElement).checked);
  }

  protected async save(): Promise<void> {
    this.saving.set(true);
    this.message.set(null);
    try {
      await this.settingsService.update({
        paper_notional: this.paperNotional(),
        risk_equity: this.riskEquity() ?? undefined,
        risk_pct: this.riskPct(),
        alert_move_pct: this.alertMovePct(),
        alert_stop_pct: this.alertStopPct(),
        alert_volume_mult: this.alertVolumeMult(),
        alerts_enabled: this.alertsEnabled(),
        daily_sweep_enabled: this.dailySweepEnabled(),
      });
      this.message.set('Settings saved.');
    } catch {
      this.message.set("Couldn't save settings.");
    } finally {
      this.saving.set(false);
    }
  }

  protected async syncWebull(): Promise<void> {
    this.syncing.set(true);
    this.message.set(null);
    try {
      const result = await this.settingsService.webullSync();
      this.message.set(result.message);
    } catch (err) {
      const detail = (err as { error?: { detail?: string } })?.error?.detail;
      this.message.set(detail ?? "Couldn't sync Webull.");
    } finally {
      this.syncing.set(false);
    }
  }
}
