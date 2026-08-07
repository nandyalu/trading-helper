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
  ColorType,
  IChartApi,
  ISeriesApi,
  LineData,
  LineSeries,
  Time,
  createChart,
} from 'lightweight-charts';

import { readChartTheme, watchTheme } from './chart-theme';

export interface LineChartPoint {
  time: string;
  value: number;
}

@Component({
  selector: 'app-line-chart',
  template: `<div #container class="chart-container"></div>`,
  styles: `
    .chart-container {
      width: 100%;
      height: var(--chart-height, 15rem);
    }
  `,
})
export class LineChart {
  readonly points = input<LineChartPoint[]>([]);
  readonly color = input<string | null>(null);

  private readonly containerRef = viewChild.required<ElementRef<HTMLDivElement>>('container');
  private readonly destroyRef = inject(DestroyRef);
  private chart?: IChartApi;
  private series?: ISeriesApi<'Line'>;

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
        grid: { vertLines: { visible: false }, horzLines: { color: theme.grid } },
        rightPriceScale: { borderVisible: false },
        timeScale: { borderVisible: false },
        width: el.clientWidth,
        height: el.clientHeight,
      });
      this.series = this.chart.addSeries(LineSeries, {
        color: this.color() ?? theme.line,
        lineWidth: 2,
      });
      this.updateData();

      const observer = new ResizeObserver(() => {
        this.chart?.applyOptions({ width: el.clientWidth, height: el.clientHeight });
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
      this.points();
      this.updateData();
    });
  }

  private applyTheme(): void {
    const theme = readChartTheme();
    this.chart?.applyOptions({
      layout: { textColor: theme.text },
      grid: { horzLines: { color: theme.grid } },
    });
    this.series?.applyOptions({ color: this.color() ?? theme.line });
  }

  private updateData(): void {
    if (!this.series) return;
    const data: LineData<Time>[] = this.points().map((p) => ({
      time: p.time as Time,
      value: p.value,
    }));
    this.series.setData(data);
    this.chart?.timeScale().fitContent();
  }
}
