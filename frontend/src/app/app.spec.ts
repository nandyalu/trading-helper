import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { App } from './app';

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
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter([])],
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
      '/scorecard',
      '/digest',
      '/regime',
      '/settings',
    ]) {
      expect(links).toContain(path);
    }
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
});
