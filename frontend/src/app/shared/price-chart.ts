import {
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  effect,
  inject,
  input,
  viewChild,
} from '@angular/core';
import {
  CandlestickData,
  CandlestickSeries,
  ColorType,
  CreatePriceLineOptions,
  IChartApi,
  IPriceLine,
  ISeriesApi,
  LineStyle,
  SeriesMarker,
  Time,
  createChart,
  createSeriesMarkers,
} from 'lightweight-charts';

import { Alert, OhlcBar, Signal, Trade } from '../core/models/api.models';
import { readChartTheme, watchTheme } from './chart-theme';

/** Decisions that read as "get in" versus "get out". Mirrors
 * BUYISH_DECISIONS / SELLISH_DECISIONS in backend/services/signals.py. */
const BUYISH = new Set(['Buy', 'Overweight']);
const SELLISH = new Set(['Sell', 'Underweight']);

const COLORS = {
  buy: '#16a34a',
  sell: '#dc2626',
  hold: '#ca8a04',
  trade: '#2563eb',
  alert: '#9333ea',
  stop: '#dc2626',
  target: '#16a34a',
};

/**
 * Candlesticks with the analysis drawn on top of them.
 *
 * The point of this component is that a price chart on its own answers almost
 * nothing useful — you can see that a stock fell, not whether the bot saw it
 * coming, whether you were holding, or whether an alert fired. Overlaying the
 * signals, trades, and alerts onto the same time axis turns the chart into the
 * record of what actually happened.
 *
 * Markers sit below the bar for entries and above it for exits, so a Buy and
 * the trade that followed it do not overlap.
 */
@Component({
  selector: 'app-price-chart',
  template: `<div #container class="chart-container"></div>`,
  styles: `
    /* Shorter on a phone, where a 360px chart pushes everything else below
       the fold. */
    .chart-container {
      width: 100%;
      height: var(--chart-height, 22.5rem);
    }
    @media (max-width: 639px) {
      .chart-container {
        height: var(--chart-height, 15rem);
      }
    }
  `,
})
export class PriceChart {
  readonly bars = input<OhlcBar[]>([]);
  readonly signals = input<Signal[]>([]);
  readonly alerts = input<Alert[]>([]);
  readonly trades = input<Trade[]>([]);
  /** Stop and target lines for the signal currently in force, if any. */
  readonly stopLevel = input<number | null>(null);
  readonly targetLevel = input<number | null>(null);

  private readonly containerRef = viewChild.required<ElementRef<HTMLDivElement>>('container');
  private readonly destroyRef = inject(DestroyRef);
  private chart?: IChartApi;
  private series?: ISeriesApi<'Candlestick'>;
  private markers?: ReturnType<typeof createSeriesMarkers<Time>>;
  private priceLines: IPriceLine[] = [];

  constructor() {
    afterNextRender(() => {
      const el = this.containerRef().nativeElement;
      const theme = readChartTheme();
      this.chart = createChart(el, {
        layout: {
          textColor: theme.text,
          background: { type: ColorType.Solid, color: 'transparent' },
          attributionLogo: false,
        },
        grid: {
          vertLines: { visible: false },
          horzLines: { color: theme.grid },
        },
        rightPriceScale: { borderVisible: false },
        timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
        crosshair: {
          horzLine: { labelBackgroundColor: theme.crosshair },
          vertLine: { labelBackgroundColor: theme.crosshair },
        },
        width: el.clientWidth,
        height: el.clientHeight,
      });
      this.series = this.chart.addSeries(CandlestickSeries, {
        upColor: COLORS.buy,
        downColor: COLORS.sell,
        borderVisible: false,
        wickUpColor: COLORS.buy,
        wickDownColor: COLORS.sell,
      });
      this.markers = createSeriesMarkers(this.series, []);
      this.render();

      const observer = new ResizeObserver(() => {
        this.chart?.applyOptions({ width: el.clientWidth, height: el.clientHeight });
        // Resizing narrower keeps the old bar spacing, which pushes the most
        // recent bars off the right edge. Re-fit so a phone-width viewport
        // shows the same range a desktop one does.
        this.chart?.timeScale().fitContent();
      });
      observer.observe(el);
      const stopWatchingTheme = watchTheme(() => this.applyTheme());
      this.destroyRef.onDestroy(() => {
        observer.disconnect();
        stopWatchingTheme();
        this.chart?.remove();
      });
    });

    effect(() => {
      // Touch every input so the effect re-runs when any of them changes.
      this.bars();
      this.signals();
      this.alerts();
      this.trades();
      this.stopLevel();
      this.targetLevel();
      this.render();
    });
  }

  private applyTheme(): void {
    const theme = readChartTheme();
    this.chart?.applyOptions({
      layout: { textColor: theme.text },
      grid: { horzLines: { color: theme.grid } },
      crosshair: {
        horzLine: { labelBackgroundColor: theme.crosshair },
        vertLine: { labelBackgroundColor: theme.crosshair },
      },
    });
  }

  private render(): void {
    if (!this.series) return;
    const data: CandlestickData<Time>[] = this.bars()
      // A bar with a missing price throws inside the candlestick renderer and
      // takes the entire chart down with it, not just the one bar. The backend
      // drops these too (get_price_history); this is the second line of
      // defense, because a blank chart is a much worse failure than a gap.
      .filter((bar) => [bar.open, bar.high, bar.low, bar.close].every(Number.isFinite))
      .map((bar) => ({
        time: bar.date as Time,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      }));
    this.series.setData(data);
    this.markers?.setMarkers(this.buildMarkers());
    this.applyPriceLines();
    // Without this the chart keeps its default bar spacing and silently clips
    // the most recent weeks — the part that matters most — whenever the
    // container is narrower than the data needs. Re-fitting on every data
    // change is safe here because changing the range is what reloads the data.
    this.chart?.timeScale().fitContent();
  }

  /** Markers must be sorted by time or lightweight-charts drops them. */
  private buildMarkers(): SeriesMarker<Time>[] {
    const markers: SeriesMarker<Time>[] = [];

    for (const signal of this.signals()) {
      const buyish = BUYISH.has(signal.decision);
      const sellish = SELLISH.has(signal.decision);
      markers.push({
        time: signal.signal_date as Time,
        position: buyish ? 'belowBar' : 'aboveBar',
        color: buyish ? COLORS.buy : sellish ? COLORS.sell : COLORS.hold,
        shape: buyish ? 'arrowUp' : sellish ? 'arrowDown' : 'circle',
        text: signal.decision,
      });
    }

    for (const trade of this.trades()) {
      const isBuy = trade.side === 'buy';
      markers.push({
        time: trade.date as Time,
        position: isBuy ? 'belowBar' : 'aboveBar',
        color: COLORS.trade,
        shape: 'square',
        text: `${isBuy ? 'Bought' : 'Sold'} ${trade.quantity}`,
      });
    }

    for (const alert of this.alerts()) {
      markers.push({
        // Alerts carry a timestamp; the chart's axis is daily bars.
        time: alert.created_at.slice(0, 10) as Time,
        position: 'aboveBar',
        color: COLORS.alert,
        shape: 'circle',
        text: '!',
      });
    }

    return markers.sort((a, b) => String(a.time).localeCompare(String(b.time)));
  }

  private applyPriceLines(): void {
    if (!this.series) return;
    for (const line of this.priceLines) this.series.removePriceLine(line);
    this.priceLines = [];

    const levels: [number | null, string, string][] = [
      [this.stopLevel(), 'Stop', COLORS.stop],
      [this.targetLevel(), 'Target', COLORS.target],
    ];
    for (const [price, title, color] of levels) {
      if (price === null) continue;
      const options: CreatePriceLineOptions = {
        price,
        color,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title,
      };
      this.priceLines.push(this.series.createPriceLine(options));
    }
  }
}
