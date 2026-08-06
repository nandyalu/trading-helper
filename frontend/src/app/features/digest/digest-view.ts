import { Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';

import { DigestService } from '../../core/services/digest.service';
import { DecisionBadge } from '../../shared/decision-badge';

@Component({
  selector: 'app-digest-view',
  imports: [RouterLink, DecisionBadge],
  templateUrl: './digest-view.html',
})
export class DigestView {
  private readonly digestService = inject(DigestService);
  protected readonly digest = this.digestService.digest;

  constructor() {
    void this.digestService.load();
  }

  protected rate(counts: [number, number]): string {
    const [passes, total] = counts;
    return total ? `${passes}/${total} (${Math.round((passes / total) * 100)}%)` : 'n/a';
  }
}
