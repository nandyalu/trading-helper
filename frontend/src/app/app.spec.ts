import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { SettingsService } from './core/services/settings.service';
import { App } from './app';

/** The shell reads one thing from settings: which deployment this is. */
class SettingsServiceStub {
  agentOnly = false;
  settings = () => ({ agent_only: this.agentOnly }) as never;
  async load(): Promise<void> {}
}

let settings: SettingsServiceStub;

interface Shell {
  drawerOpen: () => boolean;
  toggleDrawer: () => void;
  closeDrawer: () => void;
  theme: () => 'light' | 'dark';
  toggleTheme: () => void;
}

describe('App', () => {
  beforeEach(async () => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    settings = new SettingsServiceStub();
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter([]), { provide: SettingsService, useValue: settings }],
    }).compileComponents();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  it('should render the nav', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.brand')?.textContent).toContain('Trading Helper');
  });

  it('reaches every page from the drawer', async () => {
    // The bottom bar on a phone only holds four links. Anything missing from
    // the drawer would be unreachable on a small screen.
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const links = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('.sidebar a[href]'),
    ).map((a) => a.getAttribute('href'));

    for (const path of [
      '/',
      '/tickers',
      '/signals',
      '/alerts',
      '/portfolio',
      '/paper',
      '/agent',
      '/events',
      '/journey',
      '/scorecard',
      '/digest',
      '/regime',
      '/settings',
    ]) {
      expect(links).toContain(path);
    }
  });

  it('keeps the agent pages on the analyst deployment', async () => {
    // AGENT_ONLY hides the real portfolio and the paper book, which that
    // deployment does not have. It used to hide Events and Journey too,
    // because the filter matched the single path '/agent' — on the very
    // deployment those two pages exist for.
    settings.agentOnly = true;
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const links = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('.sidebar a[href]'),
    ).map((a) => a.getAttribute('href'));

    expect(links).toContain('/agent');
    expect(links).toContain('/events');
    expect(links).toContain('/journey');
    expect(links).not.toContain('/portfolio');
    expect(links).not.toContain('/paper');
  });

  it('opens and closes the drawer', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const shell = fixture.componentInstance as unknown as Shell;

    shell.toggleDrawer();
    await fixture.whenStable();
    expect(shell.drawerOpen()).toBe(true);
    expect((fixture.nativeElement as HTMLElement).querySelector('.scrim')).not.toBeNull();

    shell.closeDrawer();
    await fixture.whenStable();
    expect(shell.drawerOpen()).toBe(false);
    expect((fixture.nativeElement as HTMLElement).querySelector('.scrim')).toBeNull();
  });

  it('remembers the chosen theme', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const shell = fixture.componentInstance as unknown as Shell;

    const first = shell.theme();
    shell.toggleTheme();
    const second = shell.theme();

    expect(second).not.toBe(first);
    expect(document.documentElement.getAttribute('data-theme')).toBe(second);
    expect(localStorage.getItem('th-theme')).toBe(second);
  });

  it('hides the real and paper books in the experiment deployment', async () => {
    // Shown empty they would read as "you hold nothing", which is a different
    // statement from "there is no such book here".
    settings.agentOnly = true;
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const links = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('.sidebar a[href]'),
    ).map((a) => a.getAttribute('href'));
    expect(links).not.toContain('/portfolio');
    expect(links).not.toContain('/paper');
    expect(links).toContain('/agent');
  });

  it('shows both books in the ordinary deployment', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const links = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('.sidebar a[href]'),
    ).map((a) => a.getAttribute('href'));
    expect(links).toContain('/portfolio');
    expect(links).toContain('/paper');
    expect(links).toContain('/agent');
  });
});
