import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';

import { AgentEvent } from '../../core/models/api.models';
import { AgentService } from '../../core/services/agent.service';
import { EventsView } from './events-view';

/** A pass from 2026-09-01, the first day prompts were kept. */
function event(over: Partial<AgentEvent> = {}): AgentEvent {
  return {
    id: 1,
    ran_at: '2026-09-01T13:35:00',
    reasoning: 'Reducing overhead as cash is negative.',
    skipped: null,
    equity: 9999.4,
    cash: -8,
    research_spent: 0.6,
    prompt: 'You manage a $10,000 account…',
    response: '{"reasoning": "…", "orders": []}',
    orders: [{ side: 'untrack', ticker: 'CRM', quantity: 0, reason: 'No shares held.' }],
    refused: [],
    ...over,
  };
}

class AgentServiceStub {
  readonly events = signal<AgentEvent[]>([]);
  readonly journey = signal([]);
  async loadEvents(): Promise<void> {}
  async loadJourney(): Promise<void> {}
}

describe('EventsView', () => {
  let service: AgentServiceStub;

  beforeEach(async () => {
    service = new AgentServiceStub();
    await TestBed.configureTestingModule({
      imports: [EventsView],
      providers: [{ provide: AgentService, useValue: service }],
    }).compileComponents();
  });

  /** The component clears `loading` in a `finally`, so the skeleton is still on
   * screen until the stub's promise has settled. */
  async function render(): Promise<HTMLElement> {
    const fixture = TestBed.createComponent(EventsView);
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  it('hides the prompt until it is asked for', async () => {
    // A prompt runs to tens of kilobytes. A feed that opens with one is a feed
    // nobody scrolls.
    service.events.set([event()]);

    const el = await render();

    expect(el.querySelector('.verbatim')).toBeNull();
    expect(el.textContent).toContain('Show the prompt');
  });

  it('shows the prompt verbatim once opened', async () => {
    service.events.set([event()]);
    const fixture = TestBed.createComponent(EventsView);
    await fixture.whenStable();

    fixture.componentInstance.toggle(1, 'prompt');
    await fixture.whenStable();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.verbatim')?.textContent).toContain('You manage a $10,000 account');
  });

  it('lists what the pass actually did', async () => {
    service.events.set([event()]);

    const el = await render();

    expect(el.textContent).toContain('untrack');
    expect(el.textContent).toContain('CRM');
  });

  it('shows a refusal with its reason', async () => {
    // The interesting half. "1 rejected" says nothing; the reason is a finding.
    service.events.set([
      event({
        orders: [],
        refused: [
          {
            ticker: 'NVDA',
            side: 'buy',
            quantity: 2,
            reason: null,
            why: 'costs more than the cash left',
          },
        ],
      }),
    ]);

    expect((await render()).textContent).toContain('costs more than the cash left');
  });

  it('says a pass kept no prompt rather than showing an empty panel', async () => {
    // Every pass before 2026-09-01. The prompt cannot be reconstructed, and a
    // blank panel would read as a bug.
    service.events.set([event({ prompt: null, response: null })]);

    const el = await render();

    expect(el.textContent).toContain('kept no prompt');
    expect(el.textContent).not.toContain('Show the prompt');
  });

  it('reports a pass that did nothing as nothing, not as blank', async () => {
    service.events.set([event({ orders: [], refused: [] })]);

    expect((await render()).textContent).toContain('nothing');
  });

  it('says why a pass was skipped', async () => {
    service.events.set([event({ skipped: 'the market was shut', orders: [] })]);

    expect((await render()).textContent).toContain('the market was shut');
  });

  it('says the feed is empty rather than rendering nothing at all', async () => {
    expect((await render()).textContent).toContain('No decision passes recorded yet');
  });
});
