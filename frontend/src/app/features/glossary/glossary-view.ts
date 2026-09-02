import { Component } from '@angular/core';

import { TERMS } from '../../shared/glossary/terms';

/**
 * Every term, in one place.
 *
 * The tooltips help someone mid-sentence. This helps someone who would rather
 * understand the vocabulary before reading anything, which is a real way to
 * approach an unfamiliar subject and one the tooltips serve badly.
 *
 * Same source as the tooltips, so the two cannot disagree.
 */
@Component({
  selector: 'app-glossary-view',
  templateUrl: './glossary-view.html',
})
export class GlossaryView {
  protected readonly terms = [...TERMS].sort((a, b) => a.label.localeCompare(b.label));
}
