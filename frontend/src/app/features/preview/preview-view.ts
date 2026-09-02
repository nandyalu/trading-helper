import { Component, signal } from '@angular/core';

import { EquityChart, EquityPoint } from '../../shared/equity-chart';

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
  imports: [EquityChart],
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
