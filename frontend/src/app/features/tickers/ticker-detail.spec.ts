import { Component, input } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';

import {
  Alert,
  OhlcBar,
  Signal,
  TickerDetail,
  TickerEvents,
  Trade,
} from '../../core/models/api.models';
import { TickersService } from '../../core/services/tickers.service';
import { PriceChart } from '../../shared/price-chart';
import { TickerDetailPage } from './ticker-detail';

/** Stands in for the real chart. lightweight-charts draws to a canvas, which
 * jsdom does not implement, so instantiating it here throws on every render
 * and tells us nothing about the logic under test. */
@Component({
  selector: 'app-price-chart',
  template: '',
})
class PriceChartStub {
  readonly bars = input<OhlcBar[]>([]);
  readonly signals = input<Signal[]>([]);
  readonly alerts = input<Alert[]>([]);
  readonly trades = input<Trade[]>([]);
  readonly stopLevel = input<number | null>(null);
  readonly targetLevel = input<number | null>(null);
}

const EVENTS: TickerEvents = {
  ticker: 'NVDA',
  bars: [
    { date: '2026-08-01', open: 170, high: 176, low: 169, close: 175, volume: 1000 },
    { date: '2026-08-04', open: 175, high: 182, low: 174, close: 180, volume: 1200 },
  ],
  signals: [
    {
      id: 2,
      ticker: 'NVDA',
      signal_date: '2026-08-04',
      decision: 'Buy',
      rationale: '',
      time_horizon_text: '1-2 weeks',
      price_target: 210,
      price_at_signal: 180,
      evaluation_date: '2026-08-18',
      price_at_evaluation: null,
      outcome: null,
      evaluated_at: null,
      message_id: null,
      benchmark_price_at_signal: null,
      benchmark_price_at_evaluation: null,
      alpha_pct: null,
      outcome_vs_benchmark: null,
      price_target_hit: null,
      horizon: 'swing',
      entry_price: 180,
      stop_loss: 168,
      win_probability: 64,
      risk_reward: 2.5,
      expected_value_r: 0.75,
    },
    {
      id: 1,
      ticker: 'NVDA',
      signal_date: '2026-07-01',
      decision: 'Hold',
      rationale: '',
      time_horizon_text: null,
      price_target: null,
      price_at_signal: 150,
      evaluation_date: '2026-07-15',
      price_at_evaluation: 155,
      outcome: 'pass',
      evaluated_at: null,
      message_id: null,
      benchmark_price_at_signal: null,
      benchmark_price_at_evaluation: null,
      alpha_pct: null,
      outcome_vs_benchmark: null,
      price_target_hit: null,
      horizon: 'swing',
      entry_price: null,
      stop_loss: 140,
      win_probability: null,
      risk_reward: null,
      expected_value_r: null,
    },
  ],
  alerts: [
    {
      id: 5,
      ticker: 'NVDA',
      alert_type: 'big_move',
      message: 'NVDA moved +6.1% today.',
      created_at: '2026-08-03T14:00:00Z',
    },
  ],
  trades: [{ book: 'real', side: 'buy', date: '2026-07-08', price: 155, quantity: 10 }],
};

const DETAIL: TickerDetail = {
  ticker: 'NVDA',
  current_price: 180,
  price_updated_at: '2026-08-06T10:00:00Z',
  real_position: null,
  paper_position: null,
  latest_signal: null,
};

class TickersServiceStub {
  async getDetail(): Promise<TickerDetail> {
    return DETAIL;
  }
  async getEvents(): Promise<TickerEvents> {
    return EVENTS;
  }
}

interface Exposed {
  timeline: () => { kind: string; date: string; title: string; outcome?: string | null }[];
  activeSignal: () => { id: number } | null;
  stopLevel: () => number | null;
  targetLevel: () => number | null;
  stopDistancePct: () => number | null;
  targetDistancePct: () => number | null;
}

describe('TickerDetailPage', () => {
  async function create(): Promise<Exposed> {
    await TestBed.configureTestingModule({
      imports: [TickerDetailPage],
      providers: [
        { provide: TickersService, useClass: TickersServiceStub },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: () => 'NVDA' } } },
        },
        provideRouter([]),
      ],
    })
      .overrideComponent(TickerDetailPage, {
        remove: { imports: [PriceChart] },
        add: { imports: [PriceChartStub] },
      })
      .compileComponents();
    const fixture = TestBed.createComponent(TickerDetailPage);
    await fixture.whenStable();
    return fixture.componentInstance as unknown as Exposed;
  }

  it('merges signals, alerts, and trades into one newest-first timeline', async () => {
    const c = await create();
    const kinds = c.timeline().map((e) => `${e.date}:${e.kind}`);
    expect(kinds).toEqual([
      '2026-08-04:signal',
      '2026-08-03:alert',
      '2026-07-08:trade',
      '2026-07-01:signal',
    ]);
  });

  it('carries the graded outcome onto the timeline entry', async () => {
    const c = await create();
    const old = c.timeline().find((e) => e.date === '2026-07-01');
    expect(old?.outcome).toBe('pass');
  });

  it('draws the newest signal levels, not an older one', async () => {
    // An older signal's stop was superseded, not merely graded — drawing it
    // would put a stale line on the chart.
    const c = await create();
    expect(c.activeSignal()?.id).toBe(2);
    expect(c.stopLevel()).toBe(168);
    expect(c.targetLevel()).toBe(210);
  });

  it('measures stop and target distance from the current price', async () => {
    const c = await create();
    // Price 180, stop 168 → -6.7%; target 210 → +16.7%.
    expect(c.stopDistancePct()).toBeCloseTo(-6.67, 1);
    expect(c.targetDistancePct()).toBeCloseTo(16.67, 1);
  });
});
