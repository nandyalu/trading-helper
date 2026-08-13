import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { Settings } from '../../core/models/api.models';
import { SettingsService } from '../../core/services/settings.service';
import { SettingsView } from './settings-view';

const SERVER_SETTINGS: Settings = {
  horizon: 'position',
  llm_model: 'gemma4-e2b-96k',
  llm_model_choices: ['gemma4-e2b-96k', 'adityakale/kotakneo:latest'],
  paper_notional: 1000,
  risk_equity: 2800,
  risk_pct: 1,
  max_position_pct: 20,
  max_positions: 5,
  alert_move_pct: 5,
  alert_stop_pct: 10,
  alert_volume_mult: 2,
  alerts_enabled: true,
  daily_sweep_enabled: true,
  agent_enabled: false,
  agent_budget: 1000,
};

/** Stands in for the HTTP-backed service: records what was sent, and lets a
 * test drive the settings signal directly. */
class SettingsServiceStub {
  settingsValue: Settings | null = null;
  patches: Partial<Settings>[] = [];
  /** What load() will report — a test that needs a different server state
   * replaces this before creating the component. */
  serverSettings: Settings = SERVER_SETTINGS;

  readonly settings = () => this.settingsValue;

  async load(): Promise<void> {
    this.settingsValue = this.serverSettings;
  }

  async update(patch: Partial<Settings>): Promise<void> {
    this.patches.push(patch);
    this.settingsValue = { ...this.serverSettings, ...patch } as Settings;
  }

  async webullSync() {
    return { message: 'synced' };
  }
}

describe('SettingsView', () => {
  let service: SettingsServiceStub;

  beforeEach(async () => {
    service = new SettingsServiceStub();
    await TestBed.configureTestingModule({
      imports: [SettingsView],
      // The page links to /agent, so RouterLink needs a router even though no
      // test navigates.
      providers: [{ provide: SettingsService, useValue: service }, provideRouter([])],
    }).compileComponents();
  });

  it('offers both trade horizons', async () => {
    const fixture = TestBed.createComponent(SettingsView);
    await fixture.whenStable();
    const options = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('select option'),
    ).map((o) => (o as HTMLOptionElement).value);
    expect(options).toContain('swing');
    expect(options).toContain('position');
  });

  it('shows the horizon the server reports, not the local default', async () => {
    const fixture = TestBed.createComponent(SettingsView);
    await fixture.whenStable();
    const select = (fixture.nativeElement as HTMLElement).querySelector(
      'select',
    ) as HTMLSelectElement;
    expect(select.value).toBe('position');
  });

  it('sends the sizing limits on save', async () => {
    const fixture = TestBed.createComponent(SettingsView);
    await fixture.whenStable();

    const component = fixture.componentInstance as unknown as {
      save: () => Promise<void>;
    };
    await component.save();

    expect(service.patches).toHaveLength(1);
    const patch = service.patches[0];
    // The caps are the point of the change — a save that silently dropped
    // them would reset the account's protection to the server default.
    expect(patch.max_position_pct).toBe(20);
    expect(patch.max_positions).toBe(5);
    expect(patch.horizon).toBe('position');
  });

  it('lists the models the endpoint serves, with the current one selected', async () => {
    const fixture = TestBed.createComponent(SettingsView);
    await fixture.whenStable();
    const selects = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('select'),
    ) as HTMLSelectElement[];
    const modelSelect = selects.find((s) =>
      Array.from(s.options).some((o) => o.value === 'adityakale/kotakneo:latest'),
    );
    expect(modelSelect).toBeTruthy();
    expect(modelSelect!.value).toBe('gemma4-e2b-96k');

    // The option's own selected flag, not just the select's value. Binding
    // [value] on the select passed this check in a test while failing in a
    // browser, because whenStable() grants an extra change-detection pass that
    // the real render does not — so assert the thing that actually decides
    // what is displayed.
    const chosen = Array.from(modelSelect!.options).filter((o) => o.selected);
    expect(chosen.map((o) => o.value)).toEqual(['gemma4-e2b-96k']);
  });

  it('keeps the stored model when another setting is saved', async () => {
    // The reported symptom: change the budget, save, and the model comes back
    // as whatever sorts first. It only ever happened because the dropdown was
    // already showing the wrong option.
    const fixture = TestBed.createComponent(SettingsView);
    await fixture.whenStable();

    const component = fixture.componentInstance as unknown as { save: () => Promise<void> };
    await component.save();

    expect(service.patches[0].llm_model).toBe('gemma4-e2b-96k');
  });

  it('falls back to a text field when the endpoint could not be listed', async () => {
    // An unreachable Ollama pool must not leave the page with no way to name a
    // model — the setting is still perfectly changeable.
    service.serverSettings = { ...SERVER_SETTINGS, llm_model_choices: [] };
    const fixture = TestBed.createComponent(SettingsView);
    await fixture.whenStable();
    const input = (fixture.nativeElement as HTMLElement).querySelector(
      'input[type="text"]',
    ) as HTMLInputElement;
    expect(input.value).toBe('gemma4-e2b-96k');
  });

  it('renders inputs for both sizing caps', async () => {
    const fixture = TestBed.createComponent(SettingsView);
    await fixture.whenStable();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Most of equity in one position');
    expect(text).toContain('Most positions open at once');
  });
});
