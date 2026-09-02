import { Component } from '@angular/core';

import { Logo } from '../../shared/logo';

/**
 * Why this exists, who built it, and what did not work.
 *
 * **The draft is Claude's; the voice has to be nandyalu's.** Everything here is
 * assembled from CLAUDE.md, the journal and the benchmark write-ups, which
 * means it is accurate and it is not personal. The page is marked as a draft
 * until that is fixed, because a first-person story written by someone else is
 * the one thing on this site that would be dishonest.
 *
 * The second half is the part that earns trust with a technical reader: what
 * was tried, what failed, and what it cost. Publishing the failures is what
 * separates an experiment from a product page.
 */
@Component({
  selector: 'app-idea-view',
  imports: [Logo],
  templateUrl: './idea-view.html',
})
export class IdeaView {}
