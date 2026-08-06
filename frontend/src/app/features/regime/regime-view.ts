import { Component, inject } from '@angular/core';

import { RegimeService } from '../../core/services/regime.service';

@Component({
  selector: 'app-regime-view',
  templateUrl: './regime-view.html',
})
export class RegimeView {
  private readonly regimeService = inject(RegimeService);
  protected readonly regime = this.regimeService.regime;

  constructor() {
    void this.regimeService.load();
  }
}
