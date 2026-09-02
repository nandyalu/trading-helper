import { Component, computed, input } from '@angular/core';

import { TERMS_BY_ID } from './terms';

/**
 * A word with its definition attached.
 *
 * **A tooltip explains a word. It never carries a fact you would otherwise
 * miss.** A reader on a phone who never discovers the tap target must lose
 * nothing real — so nothing load-bearing goes in one, and everything here also
 * lives on the glossary page.
 *
 * Built on `<details>` rather than a hover popover: hover does not exist on a
 * touch screen, and a native disclosure is keyboard-reachable and
 * screen-reader-announced without any of it being reimplemented.
 */
@Component({
  selector: 'app-term',
  template: `
    @if (term(); as t) {
      <details class="term">
        <summary class="term-word">{{ t.label }}</summary>
        <span class="term-def">
          {{ t.short }}
          <a class="term-more" [href]="'/glossary#' + t.id">Glossary</a>
        </span>
      </details>
    } @else {
      <!-- An unknown key renders the raw word rather than nothing. A missing
           definition should look like a missing definition, not like a hole. -->
      <span>{{ key() }}</span>
    }
  `,
})
export class Term {
  readonly key = input.required<string>();
  protected readonly term = computed(() => TERMS_BY_ID.get(this.key()));
}
