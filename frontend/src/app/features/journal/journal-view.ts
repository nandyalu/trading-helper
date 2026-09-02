import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';

import { AgentService } from '../../core/services/agent.service';

/**
 * The last ten days of the journal the app writes about itself.
 *
 * Every sentence comes from a trade, a charge, a decision pass or a graded
 * signal, so it cannot drift from the book. The half it cannot write — why
 * *we* changed something — lives in JOURNEY.md and is not shown here.
 *
 * Served from `journey.build()`, the same source the monthly markdown files
 * come from, so the page and the files can never disagree.
 */
@Component({
  selector: 'app-journal-view',
  standalone: true,
  imports: [DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './journal-view.html',
})
export class JournalView {
  private readonly agent = inject(AgentService);
  readonly entries = this.agent.journey;
  readonly loading = signal(true);

  constructor() {
    void this.agent.loadJourney(10).finally(() => this.loading.set(false));
  }

  /** The generated markdown, minus its heading line.
   *
   * `to_markdown` renders each day under its own `##` date heading, and the
   * card already shows that date. Printing both reads as a stutter.
   */
  body(markdown: string): string {
    return markdown
      .split('\n')
      .filter((line) => !line.startsWith('#'))
      .join('\n')
      .trim();
  }
}
