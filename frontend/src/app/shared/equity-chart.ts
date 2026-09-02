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
  BaselineData,
  BaselineSeries,
  ColorType,
  IChartApi,
  ISeriesApi,
  Time,
  createChart,
} from 'lightweight-charts';

import { readChartTheme, watchTheme } from './chart-theme';

export interface EquityPoint {
  time: string;
  value: number;
}

/**
 * The equity curve, drawn against the budget it started with.
 *
 * **A baseline series, not a line.** The question a visitor asks first is "is
 * it up or down on where it started", and a plain line makes them find the
 * starting value, find today's, and compare. A baseline fills green above the
 * starting line and red below it, so the answer arrives before any number is
 * read.
 *
 * The baseline is the budget, passed in rather than inferred from the first
 * point. Those differ: the curve begins on the day of the first fill, by which
 * time some cash may already have gone on research, so the first point is not
 * the number the agent was given.
 *
 * **Colour is never the only signal.** Roughly one man in twelve cannot
 * separate this red from this green — the validator puts the pair at ΔE 6.7 for
 * deuteranopia. The figure beside the chart carries a sign and an arrow, and
 * the caption says which direction is which. The fill is a fast read for people
 * who can use it, not the only way to get the answer.
 */
@Component({
  selector: 'app-equity-chart',
  template: `<div #container class="chart-container"></div>`,
  styles: `
    .chart-container {
      width: 100%;
      height: var(--chart-height, 17rem);
    }
  `,
})
export class EquityChart {
  readonly points = input<EquityPoint[]>([]);
  /** The budget. The line green is measured above and red below. */
  readonly baseline = input<number>(0);

  private readonly containerRef = viewChild.required<ElementRef<HTMLDivElement>>('container');
  private readonly destroyRef = inject(DestroyRef);
  private chart?: IChartApi;
  private series?: ISeriesApi<'Baseline'>;

  constructor() {
    afterNextRender(() => {
      const el = this.containerRef().nativeElement;
      this.chart = createChart(el, {
        ...this.layout(),
        width: el.clientWidth,
        height: el.clientHeight,
        // The crosshair is the interaction this chart ships with: a reader
        // should be able to ask "what was it on the 22nd" without a tooltip
        // library.
        crosshair: { mode: 1 },
        handleScale: false,
        handleScroll: false,
      });
      this.series = this.chart.addSeries(BaselineSeries, this.seriesOptions());
      this.draw();

      // Guarded: jsdom has no ResizeObserver, and a chart that throws during
      // setup takes the whole page down with it. Without one the chart simply
      // does not follow a window resize, which is a smaller loss.
      const resize =
        typeof ResizeObserver === 'undefined'
          ? null
          : new ResizeObserver(() => this.chart?.applyOptions({ width: el.clientWidth }));
      resize?.observe(el);

      // Canvas cannot inherit a CSS variable, so the theme is read at creation
      // and again on every change. A chart that skips this keeps its old axis
      // colours until the page is reloaded.
      const stop = watchTheme(() => {
        this.chart?.applyOptions(this.layout());
        this.series?.applyOptions(this.seriesOptions());
      });

      this.destroyRef.onDestroy(() => {
        resize?.disconnect();
        stop();
        this.chart?.remove();
      });
    });

    effect(() => {
      this.points();
      this.baseline();
      this.draw();
    });
  }

  private layout() {
    const theme = readChartTheme();
    return {
      layout: {
        textColor: theme.text,
        background: { type: ColorType.Solid, color: 'transparent' },
        attributionLogo: false,
        fontFamily: getComputedStyle(document.body).getPropertyValue('--font'),
      },
      // Horizontal rules only. Vertical ones add ink and answer nothing on a
      // daily series.
      grid: { vertLines: { visible: false }, horzLines: { color: theme.grid } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
    };
  }

  private seriesOptions() {
    const css = getComputedStyle(document.body);
    // The chart's own pair, not the text pair. A number in prose needs 4.5:1
    // contrast, which on a dark ground pushes the red lighter than the chart's
    // lightness band allows — so the two are separate tokens. See theme.css.
    const pos = css.getPropertyValue('--chart-pos').trim();
    const neg = css.getPropertyValue('--chart-neg').trim();
    return {
      baseValue: { type: 'price' as const, price: this.baseline() },
      topLineColor: pos,
      topFillColor1: this.fade(pos, 0.28),
      topFillColor2: this.fade(pos, 0.02),
      bottomLineColor: neg,
      bottomFillColor1: this.fade(neg, 0.02),
      bottomFillColor2: this.fade(neg, 0.28),
      lineWidth: 2 as const,
      priceLineVisible: false,
      lastValueVisible: false,
    };
  }

  /** A hex token at an alpha. The chart takes colour strings rather than CSS
   * variables, so the token has to be resolved and given an alpha here. */
  private fade(hex: string, alpha: number): string {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
    if (!m) return hex;
    const n = parseInt(m[1], 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
  }

  private draw(): void {
    if (!this.series) return;
    const data: BaselineData<Time>[] = this.points().map((p) => ({
      time: p.time as Time,
      value: p.value,
    }));
    this.series.setData(data);
    this.series.applyOptions(this.seriesOptions());
    this.chart?.timeScale().fitContent();
  }
}
