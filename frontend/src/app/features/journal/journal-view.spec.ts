import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';

import { JourneyEntry } from '../../core/models/api.models';
import { AgentService } from '../../core/services/agent.service';
import { JournalView } from './journal-view';

class AgentServiceStub {
  readonly events = signal([]);
  readonly journey = signal<JourneyEntry[]>([]);
  async loadEvents(): Promise<void> {}
  async loadJourney(): Promise<void> {}
}

describe('JournalView', () => {
  let service: AgentServiceStub;

  beforeEach(async () => {
    service = new AgentServiceStub();
    await TestBed.configureTestingModule({
      imports: [JournalView],
      providers: [{ provide: AgentService, useValue: service }],
    }).compileComponents();
  });

  async function render(): Promise<HTMLElement> {
    const fixture = TestBed.createComponent(JournalView);
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  it('shows the day and its generated note', async () => {
    service.journey.set([
      { date: '2026-08-28', markdown: '## 2026-08-28\n- Bought 260 SMCI at $38.49.' },
    ]);

    const el = await render();

    expect(el.textContent).toContain('Bought 260 SMCI');
  });

  it('drops the markdown heading, because the card already shows the date', async () => {
    // Printing both reads as a stutter.
    const fixture = TestBed.createComponent(JournalView);
    await fixture.whenStable();

    const body = fixture.componentInstance.body('## 2026-08-28\n- Bought 260 SMCI.');

    expect(body).toBe('- Bought 260 SMCI.');
  });

  it('keeps a day on which nothing happened', async () => {
    // "Nothing happened" is a fact about the day, not a gap in the record.
    service.journey.set([
      { date: '2026-08-26', markdown: '## 2026-08-26\n**2026-08-26** — nothing bought or sold.' },
    ]);

    expect((await render()).textContent).toContain('nothing bought or sold');
  });

  it('says the journal is empty rather than rendering a blank page', async () => {
    expect((await render()).textContent).toContain('Nothing recorded yet');
  });
});
