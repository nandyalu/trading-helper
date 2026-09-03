import { Component, effect, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { SettingsService } from '../../core/services/settings.service';
import { marketTime } from '../../shared/market-time';

@Component({
  selector: 'app-settings-view',
  imports: [RouterLink],
  templateUrl: './settings-view.html',
})
export class SettingsView {
  /** When the daily grading run happens, on the reader's clock. */
  readonly dailySignalsTime = marketTime(21, 30);

  private readonly settingsService = inject(SettingsService);
  protected readonly settings = this.settingsService.settings;

  protected readonly horizon = signal('swing');
  protected readonly llmModel = signal('');
  protected readonly llmModelChoices = signal<string[]>([]);
  protected readonly alertMovePct = signal(5);
  protected readonly alertStopPct = signal(10);
  protected readonly alertVolumeMult = signal(2);
  protected readonly alertsEnabled = signal(true);
  protected readonly dailySweepEnabled = signal(true);
  protected readonly agentEnabled = signal(false);
  protected readonly agentBudget = signal(1000);
  // Zero means no floor, which is the default — see the template's hint.
  protected readonly agentMinWinProbability = signal(0);
  protected readonly agentMinRiskReward = signal(0);

  protected readonly saving = signal(false);
  protected readonly message = signal<string | null>(null);

  constructor() {
    effect(() => {
      const s = this.settings();
      if (!s) return;
      this.horizon.set(s.horizon);
      this.llmModel.set(s.llm_model);
      this.llmModelChoices.set(s.llm_model_choices);
      this.alertMovePct.set(s.alert_move_pct);
      this.alertStopPct.set(s.alert_stop_pct);
      this.alertVolumeMult.set(s.alert_volume_mult);
      this.alertsEnabled.set(s.alerts_enabled);
      this.dailySweepEnabled.set(s.daily_sweep_enabled);
      this.agentEnabled.set(s.agent_enabled);
      this.agentBudget.set(s.agent_budget);
      this.agentMinWinProbability.set(s.agent_min_win_probability);
      this.agentMinRiskReward.set(s.agent_min_risk_reward);
    });
    void this.settingsService.load();
  }

  protected onHorizonChange(e: Event): void {
    this.horizon.set((e.target as HTMLSelectElement).value);
  }

  protected onLlmModelChange(e: Event): void {
    this.llmModel.set((e.target as HTMLSelectElement | HTMLInputElement).value);
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

  protected onAgentEnabledChange(e: Event): void {
    this.agentEnabled.set((e.target as HTMLInputElement).checked);
  }

  protected onAgentBudgetInput(e: Event): void {
    this.agentBudget.set(Number((e.target as HTMLInputElement).value));
  }

  protected onMinWinProbabilityInput(e: Event): void {
    this.agentMinWinProbability.set(Number((e.target as HTMLInputElement).value));
  }

  protected onMinRiskRewardInput(e: Event): void {
    this.agentMinRiskReward.set(Number((e.target as HTMLInputElement).value));
  }

  protected async save(): Promise<void> {
    this.saving.set(true);
    this.message.set(null);
    try {
      await this.settingsService.update({
        horizon: this.horizon(),
        // Omitted rather than sent empty: the signal is blank until the first
        // load lands, and an empty model is a 400.
        llm_model: this.llmModel() || undefined,
        alert_move_pct: this.alertMovePct(),
        alert_stop_pct: this.alertStopPct(),
        alert_volume_mult: this.alertVolumeMult(),
        alerts_enabled: this.alertsEnabled(),
        daily_sweep_enabled: this.dailySweepEnabled(),
        agent_enabled: this.agentEnabled(),
        agent_budget: this.agentBudget(),
        agent_min_win_probability: this.agentMinWinProbability(),
        agent_min_risk_reward: this.agentMinRiskReward(),
      });
      this.message.set('Settings saved.');
    } catch (err) {
      // The API rejects a few values by name (an unknown model, an out-of-range
      // threshold); its reason is more use than "couldn't save".
      const detail = (err as { error?: { detail?: string } })?.error?.detail;
      this.message.set(detail ?? "Couldn't save settings.");
    } finally {
      this.saving.set(false);
    }
  }
}
