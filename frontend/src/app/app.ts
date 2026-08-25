import { Component, computed, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';

import { SettingsService } from './core/services/settings.service';

/** One destination in the sidebar. `icon` names a symbol in the sprite at the
 * top of app.html. */
interface NavItem {
  path: string;
  label: string;
  icon: string;
  exact?: boolean;
}

const THEME_KEY = 'th-theme';

/**
 * The application shell.
 *
 * One list of destinations is drawn three ways: a fixed sidebar on a desktop,
 * a slide-in drawer below 1024px, and a bottom bar of the four pages worth a
 * thumb tap on a phone. The bar and the drawer share the same links, so a
 * page can never become reachable on one screen size and not another.
 */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
  host: { '(document:keydown.escape)': 'closeDrawer()' },
})
export class App {
  private readonly router = inject(Router);
  private readonly settingsService = inject(SettingsService);

  /** Grouped so eleven links do not read as one undifferentiated column.
   * "Today" is what needs a decision now; "Track record" is evidence about
   * how well the bot has done. */
  protected readonly primaryNav: NavItem[] = [
    { path: '/', label: 'Overview', icon: 'grid', exact: true },
    { path: '/tickers', label: 'Tickers', icon: 'list' },
    { path: '/signals', label: 'Signals', icon: 'activity' },
    { path: '/alerts', label: 'Alerts', icon: 'bell' },
  ];

  /** True when this deployment is the autonomous-analyst experiment, which
   * has no real portfolio and no hand-followed paper book. Those pages are
   * hidden rather than shown empty: an empty Portfolio reads as "you hold
   * nothing", which is a different statement from "there is no such book
   * here". */
  private readonly agentOnly = signal(false);

  private readonly allBookNav: NavItem[] = [
    { path: '/portfolio', label: 'Portfolio', icon: 'briefcase' },
    { path: '/paper', label: 'Paper book', icon: 'file' },
    { path: '/agent', label: 'Auto trader', icon: 'zap' },
  ];

  protected readonly bookNav = computed(() =>
    this.agentOnly() ? this.allBookNav.filter((item) => item.path === '/agent') : this.allBookNav,
  );

  protected readonly recordNav: NavItem[] = [
    { path: '/scorecard', label: 'Scorecard', icon: 'target' },
    { path: '/digest', label: 'Weekly digest', icon: 'calendar' },
    { path: '/regime', label: 'Market regime', icon: 'compass' },
  ];

  /** The bottom bar holds four links plus a button that opens the drawer. */
  protected readonly tabNav = this.primaryNav;

  protected readonly drawerOpen = signal(false);
  protected readonly theme = signal<'light' | 'dark'>(readStoredTheme());

  private readonly url = signal(this.router.url);

  /** The section name shown in the mobile top bar, where there is no sidebar
   * to say which page this is. */
  protected readonly currentLabel = computed(() => {
    const url = this.url().split('?')[0];
    if (url === '/') return 'Overview';
    const all = [
      ...this.primaryNav,
      ...this.bookNav(),
      ...this.recordNav,
      { path: '/settings', label: 'Settings', icon: '' },
    ];
    return (
      all.find((item) => item.path !== '/' && url.startsWith(item.path))?.label ?? 'Trading Helper'
    );
  });

  constructor() {
    this.applyTheme(this.theme());
    // Which deployment this is decides what the sidebar may offer. Read once
    // at startup: it is a property of the container, not of the session, and
    // it cannot change while the page is open.
    void this.settingsService
      .load()
      .then(() => this.agentOnly.set(this.settingsService.settings()?.agent_only ?? false))
      .catch(() => this.agentOnly.set(false));
    this.router.events
      .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
      .subscribe((e) => {
        this.url.set(e.urlAfterRedirects);
        // A drawer that stays open over the page it just navigated to hides the
        // result of the tap that opened it.
        this.drawerOpen.set(false);
      });
  }

  protected toggleDrawer(): void {
    this.drawerOpen.update((open) => !open);
  }

  protected closeDrawer(): void {
    this.drawerOpen.set(false);
  }

  protected toggleTheme(): void {
    const next = this.theme() === 'dark' ? 'light' : 'dark';
    this.theme.set(next);
    this.applyTheme(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      /* Private mode blocks localStorage. The choice lasts for this page only. */
    }
  }

  private applyTheme(theme: 'light' | 'dark'): void {
    document.documentElement.setAttribute('data-theme', theme);
  }
}

/** The stored choice, or whatever the operating system asks for. index.html
 * has already applied this before the first paint; reading it again here
 * keeps the toggle button in step with what the reader sees. */
function readStoredTheme(): 'light' | 'dark' {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch {
    /* ignore */
  }
  return typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}
