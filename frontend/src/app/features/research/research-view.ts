import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { Signal } from '../../core/models/api.models';
import { SignalsService } from '../../core/services/signals.service';
import { TickersService } from '../../core/services/tickers.service';
import { WatchlistService } from '../../core/services/watchlist.service';
import { DecisionBadge } from '../../shared/decision-badge';
import { Term } from '../../shared/glossary/term';

type StatusFilter = '' | 'pending' | 'resolved';

/**
 * What the agent studies, and what each study concluded.
 *
 * This merges two pages that were always one subject. Tickers listed what was
 * being watched; Signals listed the analyses of them. Split, a reader had to
 * hold "the agent pays for each of these names every morning" on one page and
 * "here is what that money bought" on another.
 *
 * Nothing here adds or removes a ticker. The agent commissions research to add
 * a name and untracks to drop one, and it pays for every name on the list every
 * morning. The candidate list at the bottom is the same menu it is shown in its
 * prompt — it is here to be looked at, not acted on.
 */
@Component({
  selector: 'app-research-view',
  imports: [RouterLink, DecisionBadge, Term],
  templateUrl: './research-view.html',
})
export class ResearchView {
  private readonly tickersService = inject(TickersService);
  private readonly signalsService = inject(SignalsService);
  private readonly watchlistService = inject(WatchlistService);

  protected readonly tickers = this.tickersService.tickers;
  protected readonly loading = this.tickersService.loading;
  protected readonly candidates = this.watchlistService.candidates;
  protected readonly signals = this.signalsService.signals;

  protected readonly statusFilter = signal<StatusFilter>('');

  /** Newest analysis per ticker is already on the watchlist rows, so the feed
   * below is every analysis in date order — the same name appearing twice is
   * the interesting case, not a duplicate to collapse. */
  protected readonly feed = computed<Signal[]>(() => this.signals());

  /** What the watchlist costs to keep, at $0.05 an analysis every weekday.
   * The agent is shown this same figure; a reader should see what it sees. */
  protected readonly dailyCost = computed(() => this.tickers().length * 0.05);

  constructor() {
    void this.tickersService.load();
    void this.reloadSignals();
    // Not awaited with the rest: it calls the screener and is slower, and the
    // page should show what is already tracked first.
    void this.watchlistService.loadCandidates().catch(() => {});
  }

  protected async setFilter(status: StatusFilter): Promise<void> {
    this.statusFilter.set(status);
    await this.reloadSignals();
  }

  private async reloadSignals(): Promise<void> {
    const status = this.statusFilter();
    await this.signalsService.load({ status: status || undefined, limit: 50 });
  }

  protected volumeM(volume: number): string {
    return `${(volume / 1_000_000).toFixed(0)}M`;
  }
}
