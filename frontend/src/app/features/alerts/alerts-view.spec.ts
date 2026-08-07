import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { Alert } from '../../core/models/api.models';
import { AlertsService } from '../../core/services/alerts.service';
import { AlertsView } from './alerts-view';

const ALERTS: Alert[] = [
  {
    id: 2,
    ticker: 'NVDA',
    alert_type: 'signal_stop',
    message: 'NVDA at $90.00 reached the $90.00 stop.',
    created_at: '2026-08-06T14:30:00Z',
  },
  {
    id: 1,
    ticker: 'AAPL',
    alert_type: 'big_move',
    message: 'AAPL moved +6.2% today.',
    created_at: '2026-08-05T18:00:00Z',
  },
];

/** ``data`` is what the server would return; ``load()`` copies it into the
 * signal, exactly as the real service does. Setting ``data`` before creating
 * the component is therefore what controls the test — assigning the signal
 * directly would be overwritten by the constructor's own load(). */
class AlertsServiceStub {
  data: Alert[] = ALERTS;
  private value: Alert[] | null = null;
  readonly alerts = () => this.value;
  async load(): Promise<void> {
    this.value = this.data;
  }
}

describe('AlertsView', () => {
  let service: AlertsServiceStub;

  beforeEach(async () => {
    service = new AlertsServiceStub();
    await TestBed.configureTestingModule({
      imports: [AlertsView],
      providers: [{ provide: AlertsService, useValue: service }, provideRouter([])],
    }).compileComponents();
  });

  it('lists every alert', async () => {
    const fixture = TestBed.createComponent(AlertsView);
    await fixture.whenStable();
    const rows = (fixture.nativeElement as HTMLElement).querySelectorAll('tbody tr');
    expect(rows.length).toBe(2);
  });

  it('names the stop types distinctly', async () => {
    // signal_stop and stop_loss both mean a loss but for different reasons;
    // showing the raw key would hide that.
    const fixture = TestBed.createComponent(AlertsView);
    await fixture.whenStable();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Thesis broken');
    expect(text).not.toContain('signal_stop');
  });

  it('filters to one type', async () => {
    const fixture = TestBed.createComponent(AlertsView);
    await fixture.whenStable();

    const component = fixture.componentInstance as unknown as {
      filter: { set: (v: string) => void };
      visible: () => Alert[];
    };
    component.filter.set('signal_stop');
    expect(component.visible().map((a) => a.id)).toEqual([2]);
  });

  it('offers only types present in the data', async () => {
    const fixture = TestBed.createComponent(AlertsView);
    await fixture.whenStable();
    const component = fixture.componentInstance as unknown as { availableTypes: () => string[] };
    expect(component.availableTypes()).toEqual(['big_move', 'signal_stop']);
  });

  it('says so when there is nothing yet', async () => {
    service.data = [];
    const fixture = TestBed.createComponent(AlertsView);
    await fixture.whenStable();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('No alerts yet');
  });
});
