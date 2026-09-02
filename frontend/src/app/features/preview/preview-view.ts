import { Component, signal } from '@angular/core';

import { EquityChart, EquityPoint } from '../../shared/equity-chart';
import { Logo } from '../../shared/logo';
import { ClockTime, marketTime } from '../../shared/market-time';

/**
 * The design system, on real content, before it is applied to eight pages.
 *
 * **This page exists to be thrown away.** It is the cheap place to be wrong
 * about the type scale, the palette and the weight of a heading — changing any
 * of those here costs one file, and changing them after the site is built on
 * top costs all of them.
 *
 * It is deliberately not a swatch board. A palette looks fine as squares and
 * falls apart the moment it carries a hero number, a dense table and a wall of
 * monospace prompt. So every block below is content the real site actually
 * has.
 */
@Component({
  selector: 'app-preview-view',
  imports: [EquityChart, Logo],
  templateUrl: './preview-view.html',
})
export class PreviewView {
  /** A plausible fortnight: up, a drawdown, a recovery. Invented, and labelled
   * as invented on the page — a preview that looks like live data is a preview
   * somebody screenshots and publishes by mistake. */
  protected readonly curve = signal<EquityPoint[]>(
    [
      10000, 10040, 9985, 10120, 10190, 10090, 9940, 9880, 10010, 10180, 10240, 10310, 10205, 10243,
    ].map((value, i) => ({
      time: new Date(Date.UTC(2026, 7, 18 + i)).toISOString().slice(0, 10),
      value,
    })),
  );

  protected readonly holdings = [
    {
      ticker: 'NVDA',
      shares: 4,
      avgCost: 178.2,
      invested: 712.8,
      price: 191.44,
      days: 6,
      pnl: 52.96,
    },
    {
      ticker: 'MSFT',
      shares: 2,
      avgCost: 421.5,
      invested: 843.0,
      price: 414.1,
      days: 11,
      pnl: -14.8,
    },
    {
      ticker: 'GOOG',
      shares: 3,
      avgCost: 201.33,
      invested: 603.99,
      price: 208.7,
      days: 3,
      pnl: 22.11,
    },
  ];

  /** The fixed daily schedule, rendered on both clocks.
   *
   * `done` is hardcoded here because this is a preview. On the real page it
   * comes from whether the job has run, which is a fact the API reports rather
   * than a comparison against the reader's clock — a reader in Tokyo must not
   * see tomorrow's pass marked complete because it is already the next day
   * where they are. */
  private readonly yesterday = new Date(Date.UTC(2026, 7, 29));
  private readonly today = new Date(Date.UTC(2026, 8, 1));

  protected readonly friday = [
    {
      t: marketTime(11, 0, this.yesterday),
      text: 'Analysed 12 tickers. Charged $0.60.',
      done: true,
      act: false,
    },
    {
      t: marketTime(12, 45, this.yesterday),
      text: 'Regime read risk-on. VIX 16.7.',
      done: true,
      act: false,
    },
    {
      t: marketTime(13, 35, this.yesterday),
      text: 'Bought 4 NVDA. Sold 2 AAPL. Dropped CRM.',
      done: true,
      act: true,
    },
    {
      t: marketTime(21, 30, this.yesterday),
      text: 'Graded 2 signals. One beat SPY.',
      done: true,
      act: false,
    },
  ];

  protected readonly monday = [
    {
      t: marketTime(11, 0, this.today),
      text: 'Analysed 12 tickers. Charged $0.60.',
      done: true,
      act: false,
    },
    { t: marketTime(12, 45, this.today), text: 'Regime check', done: false, act: false },
    { t: marketTime(13, 0, this.today), text: 'Earnings check', done: false, act: false },
    { t: marketTime(13, 35, this.today), text: 'It decides', done: false, act: true },
    {
      t: marketTime(21, 30, this.today),
      text: 'Grading, then the journal',
      done: false,
      act: false,
    },
  ];

  /** The market's clock. Always shown, because it is the one the experiment
   * actually runs on. */
  protected marketClock(t: ClockTime): string {
    return `${t.et} ${t.etZone}`;
  }

  /** The reader's own, or empty when they are already on the market's clock —
   * printing the same time twice is noise rather than help. */
  protected readerClock(t: ClockTime): string {
    return t.local ? `${t.local} ${t.localZone}` : '';
  }

  protected readonly terms = [
    [
      'refused',
      'Python declined the order before it was sent. The agent’s own arithmetic was wrong.',
    ],
    [
      'broker said no',
      'The order was formed correctly and the broker would not take it — unsettled cash, a closed session.',
    ],
    [
      'vs SPY',
      'Whether the call beat the market over the same window. The number that actually counts.',
    ],
    ['maturing', 'Not judged yet. A swing call is graded 14 days after it is made.'],
  ];

  protected signed(value: number, digits = 2): string {
    return `${value >= 0 ? '+' : '−'}$${Math.abs(value).toFixed(digits)}`;
  }

  protected pct(pnl: number, invested: number): string {
    const p = (pnl / invested) * 100;
    return `${p >= 0 ? '+' : '−'}${Math.abs(p).toFixed(1)}%`;
  }
}
