import { Component, OnInit, inject } from '@angular/core';
import { RouterLink } from '@angular/router';

import { TickersService } from '../../core/services/tickers.service';
import { WatchlistService } from '../../core/services/watchlist.service';
import { DecisionBadge } from '../../shared/decision-badge';

/**
 * The watchlist, read-only.
 *
 * Nothing on this page adds or removes a ticker, and nothing starts an
 * analysis. The agent chooses what it watches: it commissions research with a
 * `research` action and drops a name with an `untrack` action, and it pays for
 * every ticker on the list every morning. A ticker added here would cost it
 * nothing and would read, later, as a name it chose.
 *
 * The candidates below are the same menu the agent is shown in its prompt.
 * They are here to be looked at.
 */
@Component({
  selector: 'app-ticker-list',
  imports: [RouterLink, DecisionBadge],
  templateUrl: './ticker-list.html',
})
export class TickerList implements OnInit {
  private readonly tickersService = inject(TickersService);
  private readonly watchlistService = inject(WatchlistService);

  protected readonly tickers = this.tickersService.tickers;
  protected readonly loading = this.tickersService.loading;
  protected readonly candidates = this.watchlistService.candidates;

  ngOnInit(): void {
    void this.tickersService.load();
    // Not awaited with the rest: it calls the screener and is slower, and the
    // page should show what is already tracked first.
    void this.watchlistService.loadCandidates().catch(() => {});
  }

  protected volumeM(volume: number): string {
    return `${(volume / 1_000_000).toFixed(0)}M`;
  }
}
