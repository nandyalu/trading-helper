import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';

import { AgentEvent } from '../../core/models/api.models';
import { AgentService } from '../../core/services/agent.service';
import { DecisionsView } from './decisions-view';

/** A pass from 2026-09-01, the first day prompts were kept. */
function event(over: Partial<AgentEvent> = {}): AgentEvent {
  return {
    id: 1,
    // The API stamps the offset. Without it a browser reads the instant as
    // local time, which is the bug `readerDateTime` was written to fix.
    ran_at: '2026-09-01T13:35:00Z',
    next_wakeup: null,
    reasoning: 'Reducing overhead as cash is negative.',
    skipped: null,
    equity: 9999.4,
    cash: -8,
    research_spent: 0.6,
    prompt: 'You manage a $10,000 account…',
    response: '{"reasoning": "…", "orders": []}',
    orders: [{ side: 'untrack', ticker: 'CRM', quantity: 0, reason: 'No shares held.' }],
    refused: [],
    failed: [],
    ...over,
  };
}

class AgentServiceStub {
  readonly events = signal<AgentEvent[]>([]);
  readonly journey = signal([]);
  async loadEvents(): Promise<void> {}
  async loadJourney(): Promise<void> {}
}

describe('DecisionsView', () => {
  let service: AgentServiceStub;

  beforeEach(async () => {
    service = new AgentServiceStub();
    await TestBed.configureTestingModule({
      imports: [DecisionsView],
      providers: [{ provide: AgentService, useValue: service }],
    }).compileComponents();
  });

  /** The component clears `loading` in a `finally`, so the skeleton is still on
   * screen until the stub's promise has settled. */
  async function render(): Promise<HTMLElement> {
    const fixture = TestBed.createComponent(DecisionsView);
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
    const fixture = TestBed.createComponent(DecisionsView);
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
  it('shows a note apart from the orders, and not as an order', async () => {
    // A note has no ticker and no quantity. Rendered in the orders list it
    // would read as a trade in a stock called "".
    service.events.set([
      event({
        orders: [
          { side: 'buy', ticker: 'AAPL', quantity: 2, reason: 'cheap' },
          { side: 'note', ticker: '', quantity: 0, reason: 'I cannot see sector data.' },
        ],
        refused: [],
        failed: [],
      }),
    ]);

    const el = await render();

    expect(el.querySelector('.agent-note')?.textContent).toContain('I cannot see sector data.');
    expect(el.querySelector('.orders')?.textContent).not.toContain('I cannot see sector data.');
    expect(el.querySelector('.orders')?.textContent).toContain('AAPL');
  });

  it('tells a broker failure apart from a refusal', async () => {
    // The two mean different things and the page has to say so: one is the
    // agent's arithmetic being wrong, the other is the world declining an
    // order it formed correctly.
    service.events.set([
      event({
        orders: [],
        refused: [
          { side: 'buy', ticker: 'MSFT', quantity: 9, reason: null, why: 'not enough cash' },
        ],
        failed: [
          { side: 'buy', ticker: 'NVDA', quantity: 1, reason: null, why: 'unsettled funds' },
        ],
      }),
    ]);

    const text = (await render()).textContent ?? '';

    expect(text).toContain('not enough cash');
    expect(text).toContain('unsettled funds');
    expect(text).toContain('broker said no');
  });

  /** UTC is not what anyone should read. The pass time is rendered on the
   * reader's own clock with the zone named, so it is unambiguous without a
   * second line — and the old fixed "UTC" label must not come back, because it
   * was wrong for every reader not already on UTC. */
  /** The pass time is rendered on the reader's own clock with that zone named.
   *
   * The assertion is that the time and its label agree, not that the label is
   * any particular string — on a machine in UTC, "UTC" is the correct label.
   * The old code failed exactly this: it formatted in local time and printed a
   * fixed "UTC", so the two disagreed for every reader outside UTC. Run the
   * suite under `TZ=Asia/Kolkata` to see the difference. */
  it('shows the pass time on the reader clock, with that zone named', async () => {
    service.events.set([event()]);
    const el = await render();

    const head = el.querySelector('.card-head strong')?.textContent ?? '';
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const instant = new Date('2026-09-01T13:35:00Z');

    const time = new Intl.DateTimeFormat('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      timeZone: zone,
    }).format(instant);
    const label =
      new Intl.DateTimeFormat('en-US', { timeZone: zone, timeZoneName: 'short' })
        .formatToParts(instant)
        .find((p) => p.type === 'timeZoneName')?.value ?? '';

    expect(head).toContain(time);
    expect(head).toContain(label);
  });

});
