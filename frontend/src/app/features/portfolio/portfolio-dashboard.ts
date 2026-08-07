import { Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';

import { PortfolioService } from '../../core/services/portfolio.service';

@Component({
  selector: 'app-portfolio-dashboard',
  imports: [RouterLink],
  templateUrl: './portfolio-dashboard.html',
})
export class PortfolioDashboard {
  private readonly portfolioService = inject(PortfolioService);
  protected readonly portfolio = this.portfolioService.portfolio;

  constructor() {
    void this.portfolioService.load();
  }
}
