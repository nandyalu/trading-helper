import { Component, DestroyRef, ElementRef, afterNextRender, effect, inject, input, viewChild } from '@angular/core';
import {
  CandlestickData,
  CandlestickSeries,
  ColorType,
  IChartApi,
  ISeriesApi,
  Time,
  createChart,
} from 'lightweight-charts';

import { OhlcBar } from '../core/models/api.models';

@Component({
  selector: 'app-price-chart',
  template: `<div #container class="chart-container"></div>`,
  styles: `
    .chart-container {
      width: 100%;
      height: 320px;
    }
  `,
})
export class PriceChart {
  readonly bars = input<OhlcBar[]>([]);

  private readonly containerRef = viewChild.required<ElementRef<HTMLDivElement>>('container');
  private readonly destroyRef = inject(DestroyRef);
  private chart?: IChartApi;
  private series?: ISeriesApi<'Candlestick'>;

  constructor() {
    afterNextRender(() => {
      const el = this.containerRef().nativeElement;
      this.chart = createChart(el, {
        layout: { textColor: '#888', background: { type: ColorType.Solid, color: 'transparent' } },
        grid: { vertLines: { visible: false }, horzLines: { visible: false } },
        width: el.clientWidth,
        height: 320,
      });
      this.series = this.chart.addSeries(CandlestickSeries);
      this.updateData();

      const observer = new ResizeObserver(() => this.chart?.applyOptions({ width: el.clientWidth }));
      observer.observe(el);
      this.destroyRef.onDestroy(() => {
        observer.disconnect();
        this.chart?.remove();
      });
    });

    effect(() => {
      this.bars();
      this.updateData();
    });
  }

  private updateData(): void {
    if (!this.series) return;
    const data: CandlestickData<Time>[] = this.bars().map((bar) => ({
      time: bar.date as Time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));
    this.series.setData(data);
  }
}
