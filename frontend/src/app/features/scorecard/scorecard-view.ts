import { Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';

import { DecisionStats } from '../../core/models/api.models';
import { ScorecardService } from '../../core/services/scorecard.service';
import { DecisionBadge } from '../../shared/decision-badge';

@Component({
  selector: 'app-scorecard-view',
  imports: [RouterLink, DecisionBadge],
  templateUrl: './scorecard-view.html',
})
export class ScorecardView {
  private readonly scorecardService = inject(ScorecardService);
  protected readonly scorecard = this.scorecardService.scorecard;
  protected readonly calibration = this.scorecardService.calibration;

  constructor() {
    void this.scorecardService.load();
  }

  /** A percentage-point gap, signed. Positive means the model claimed more
   * than it delivered, which is the direction that inflates every expected
   * value computed from it. */
  protected gap(value: number | null): string {
    if (value === null) return '—';
    return `${value >= 0 ? '+' : ''}${value.toFixed(0)} pts`;
  }

  protected pctOf(value: number | null): string {
    return value === null ? '—' : `${Math.round(value)}%`;
  }

  /** Count and share together, for a table cell. */
  protected rate(passes: number, total: number): string {
    return total ? `${passes}/${total} (${Math.round((passes / total) * 100)}%)` : 'n/a';
  }

  /** The share alone, for a stat tile that names the count underneath it. */
  protected pct(passes: number, total: number): string {
    return total ? `${Math.round((passes / total) * 100)}%` : '—';
  }

  protected decisionEntries(byDecision: Record<string, DecisionStats>): [string, DecisionStats][] {
    return Object.entries(byDecision);
  }

  /** Most-used model first — that is the incumbent a new one is being judged
   * against. */
  protected modelEntries(byModel: Record<string, DecisionStats>): [string, DecisionStats][] {
    return Object.entries(byModel).sort((a, b) => b[1].total - a[1].total);
  }

  protected tickerEntries(
    byTicker: Record<string, [number, number]>,
  ): [string, [number, number]][] {
    return Object.entries(byTicker)
      .sort((a, b) => b[1][1] - a[1][1])
      .slice(0, 10);
  }
}
