import { Component, DestroyRef, ElementRef, afterNextRender, effect, inject, input, viewChild } from '@angular/core';
import { ColorType, IChartApi, ISeriesApi, LineData, LineSeries, Time, createChart } from 'lightweight-charts';

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
      height: 240px;
    }
  `,
})
export class LineChart {
  readonly points = input<LineChartPoint[]>([]);
  readonly color = input('#2563eb');

  private readonly containerRef = viewChild.required<ElementRef<HTMLDivElement>>('container');
  private readonly destroyRef = inject(DestroyRef);
  private chart?: IChartApi;
  private series?: ISeriesApi<'Line'>;

  constructor() {
    afterNextRender(() => {
      const el = this.containerRef().nativeElement;
      this.chart = createChart(el, {
        layout: { textColor: '#888', background: { type: ColorType.Solid, color: 'transparent' } },
        grid: { vertLines: { visible: false }, horzLines: { visible: false } },
        width: el.clientWidth,
        height: 240,
      });
      this.series = this.chart.addSeries(LineSeries, { color: this.color() });
      this.updateData();

      const observer = new ResizeObserver(() => this.chart?.applyOptions({ width: el.clientWidth }));
      observer.observe(el);
      this.destroyRef.onDestroy(() => {
        observer.disconnect();
        this.chart?.remove();
      });
    });

    effect(() => {
      this.points();
      this.updateData();
    });
  }

  private updateData(): void {
    if (!this.series) return;
    const data: LineData<Time>[] = this.points().map((p) => ({ time: p.time as Time, value: p.value }));
    this.series.setData(data);
  }
}
