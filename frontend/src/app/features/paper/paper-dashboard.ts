import { Component, computed, inject, signal } from '@angular/core';

import { PaperService } from '../../core/services/paper.service';
import { LineChart, LineChartPoint } from '../../shared/line-chart';

@Component({
  selector: 'app-paper-dashboard',
  imports: [LineChart],
  templateUrl: './paper-dashboard.html',
})
export class PaperDashboard {
  private readonly paperService = inject(PaperService);

  protected readonly portfolio = this.paperService.portfolio;
  protected readonly closingTicker = signal<string | null>(null);
  protected readonly message = signal<string | null>(null);

  protected readonly equityCurve = computed<LineChartPoint[]>(() =>
    this.paperService.snapshots().map((s) => ({
      time: s.snapshot_date,
      value: s.open_value - s.open_cost + s.realized_pnl,
    }))
  );

  constructor() {
    void this.paperService.load();
  }

  protected async closePosition(ticker: string): Promise<void> {
    this.closingTicker.set(ticker);
    this.message.set(null);
    try {
      const result = await this.paperService.close(ticker);
      this.message.set(result.message);
    } finally {
      this.closingTicker.set(null);
    }
  }
}
