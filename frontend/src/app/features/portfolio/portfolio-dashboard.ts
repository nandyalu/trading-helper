import { Component, inject } from '@angular/core';

import { PortfolioService } from '../../core/services/portfolio.service';

@Component({
  selector: 'app-portfolio-dashboard',
  templateUrl: './portfolio-dashboard.html',
})
export class PortfolioDashboard {
  private readonly portfolioService = inject(PortfolioService);
  protected readonly portfolio = this.portfolioService.portfolio;

  constructor() {
    void this.portfolioService.load();
  }
}
