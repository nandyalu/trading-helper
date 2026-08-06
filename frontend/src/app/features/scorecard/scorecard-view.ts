import { Component, inject } from '@angular/core';

import { DecisionStats } from '../../core/models/api.models';
import { ScorecardService } from '../../core/services/scorecard.service';

@Component({
  selector: 'app-scorecard-view',
  templateUrl: './scorecard-view.html',
})
export class ScorecardView {
  private readonly scorecardService = inject(ScorecardService);
  protected readonly scorecard = this.scorecardService.scorecard;

  constructor() {
    void this.scorecardService.load();
  }

  protected rate(passes: number, total: number): string {
    return total ? `${passes}/${total} (${Math.round((passes / total) * 100)}%)` : 'n/a';
  }

  protected decisionEntries(byDecision: Record<string, DecisionStats>): [string, DecisionStats][] {
    return Object.entries(byDecision);
  }

  protected tickerEntries(byTicker: Record<string, [number, number]>): [string, [number, number]][] {
    return Object.entries(byTicker)
      .sort((a, b) => b[1][1] - a[1][1])
      .slice(0, 10);
  }
}
