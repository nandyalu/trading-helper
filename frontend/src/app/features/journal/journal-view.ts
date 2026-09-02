import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';

import { AgentService } from '../../core/services/agent.service';
import { DigestService } from '../../core/services/digest.service';

/**
 * What happened, in the app's own words: the week in summary, then the last ten
 * days one at a time.
 *
 * Every sentence in both comes from a trade, a charge, a decision pass or a
 * graded signal, so neither can drift from the book. The half the app cannot
 * write — why *we* changed something — lives in JOURNEY.md and is not shown
 * here.
 *
 * The weekly digest used to have its own page. It is the same subject at a
 * different zoom, and a reader who wants "what has been happening" should not
 * have to know which of two pages holds the answer.
 *
 * The daily entries are served from `journey.build()`, the same source the
 * monthly markdown files come from, so the page and the files cannot disagree.
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
  private readonly digestService = inject(DigestService);

  readonly entries = this.agent.journey;
  readonly digest = this.digestService.digest;
  readonly loading = signal(true);

  constructor() {
    void Promise.all([
      this.agent.loadJourney(10),
      // Never allowed to fail the page. The digest is a summary of what is
      // below it; a week that cannot be summarised should still show its days.
      this.digestService.load().catch(() => {}),
    ]).finally(() => this.loading.set(false));
  }

  rate(passes: number, total: number): string {
    return total ? `${passes}/${total} (${Math.round((passes / total) * 100)}%)` : 'n/a';
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
