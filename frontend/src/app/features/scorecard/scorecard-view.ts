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

  constructor() {
    void this.scorecardService.load();
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

  protected tickerEntries(
    byTicker: Record<string, [number, number]>,
  ): [string, [number, number]][] {
    return Object.entries(byTicker)
      .sort((a, b) => b[1][1] - a[1][1])
      .slice(0, 10);
  }
}
