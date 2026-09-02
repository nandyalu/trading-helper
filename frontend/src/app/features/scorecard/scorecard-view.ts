import { Component, computed, inject } from '@angular/core';
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

  /**
   * The verdict, in one sentence, stated plainly.
   *
   * **The most likely answer for a long time is "not enough data", and saying
   * so is the point.** A site that publishes a percentage off six resolved
   * signals is not reporting a result, it is inviting a wrong conclusion. The
   * threshold is twenty, below which a win rate is noise: three in four reads
   * as 75% and means nothing.
   *
   * Past that, the test is vs-SPY, not the absolute rate. Being right about a
   * stock in a rising market is not skill — holding the index and doing
   * nothing would have been right too.
   */
  protected readonly verdict = computed(() => {
    const s = this.scorecard();
    if (!s) return null;
    if (s.resolved === 0) {
      return {
        tone: 'waiting' as const,
        headline: 'Nothing has been graded yet.',
        detail:
          `${s.pending} ${s.pending === 1 ? 'analysis is' : 'analyses are'} still maturing. ` +
          'Each one is judged when its horizon arrives — 14 days for a swing call.',
      };
    }
    if (s.resolved < 20) {
      return {
        tone: 'waiting' as const,
        headline: `Too early to say. ${s.resolved} graded so far.`,
        detail:
          'Below about twenty resolved signals a win rate is noise, not evidence. ' +
          'The counts below are real; the percentages are not yet worth reading.',
      };
    }
    const beat = s.vs_benchmark_total ? s.vs_benchmark_passes / s.vs_benchmark_total : 0;
    const alpha = s.avg_alpha_pct ?? 0;
    const counts =
      `${s.vs_benchmark_passes} of ${s.vs_benchmark_total} calls beat SPY over their own ` +
      `window, averaging ${alpha >= 0 ? '+' : ''}${alpha.toFixed(1)}% against it.`;

    // **The hit rate and the average can disagree, and that disagreement is
    // the finding rather than an edge case to round away.** Winning most of
    // the time and still losing on average means the losses are larger than
    // the wins — which a headline reading only the hit rate would hide, and a
    // headline reading only the average would call plain failure.
    if (beat > 0.55 && alpha < 0) {
      return {
        tone: 'inconclusive' as const,
        headline: 'It is right more often than not, and still losing to the market.',
        detail:
          `${counts} Most calls beat the index and the average does not, which means the ` +
          'losses are bigger than the wins. A win rate on its own would have hidden that.',
      };
    }
    if (beat < 0.45 && alpha > 0) {
      return {
        tone: 'inconclusive' as const,
        headline: 'It is wrong more often than not, and still ahead of the market.',
        detail:
          `${counts} Fewer than half the calls beat the index and the average still does, ` +
          'which means a small number of large wins are carrying it.',
      };
    }
    if (beat > 0.55 && alpha > 0) {
      return {
        tone: 'working' as const,
        headline: 'It is beating the market, on this sample.',
        detail: `${counts} One sample, one market regime — a finding, not a conclusion.`,
      };
    }
    if (beat < 0.45 && alpha < 0) {
      return {
        tone: 'not-working' as const,
        headline: 'It is not beating the market.',
        detail: `${counts} Holding the index and doing nothing would have done better.`,
      };
    }
    return {
      tone: 'inconclusive' as const,
      headline: 'It is roughly even with the market.',
      detail: `${counts} Close enough to even that the difference is not evidence of anything.`,
    };
  });

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
