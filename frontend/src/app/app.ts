import { Component, computed, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';

import { SettingsService } from './core/services/settings.service';
import { Logo } from './shared/logo';

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
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Logo],
  templateUrl: './app.html',
  host: { '(document:keydown.escape)': 'closeDrawer()' },
})
export class App {
  private readonly router = inject(Router);
  private readonly settingsService = inject(SettingsService);

  /** Two groups, six links.
   *
   * "What it did" is the experiment as it happens; "The record" is evidence
   * about whether it worked. The old table had eleven links across three
   * groups, one per data source — a shape that suited an operator and left a
   * reader to work out which page answered their question. */
  protected readonly primaryNav: NavItem[] = [
    { path: '/', label: 'The experiment', icon: 'grid', exact: true },
    { path: '/book', label: 'The book', icon: 'zap' },
    { path: '/decisions', label: 'Decisions', icon: 'chart' },
    { path: '/research', label: 'Research', icon: 'list' },
  ];

  protected readonly recordNav: NavItem[] = [
    { path: '/scorecard', label: 'Scorecard', icon: 'target' },
    { path: '/journal', label: 'Journal', icon: 'book' },
  ];

  /** Context rather than data. These explain the experiment instead of
   * reporting it, so they sit in the footer and the drawer rather than
   * competing with the six destinations that change every day. */
  protected readonly aboutNav: NavItem[] = [
    { path: '/idea', label: 'The idea', icon: 'book' },
    { path: '/method', label: 'Method', icon: 'file' },
    { path: '/glossary', label: 'Glossary', icon: 'list' },
  ];

  /** Everything, for the narrow-screen drawer. Every route has to be reachable
   * without a sidebar, and app.spec asserts it. */
  protected readonly allNav = computed(() => [
    ...this.primaryNav,
    ...this.recordNav,
    ...this.aboutNav,
    ...(this.isPublic() ? [] : [{ path: '/settings', label: 'Settings', icon: 'sliders' }]),
  ]);

  /** True on the published copy, where the backend refuses every write.
   *
   * It hides the Settings link, and that is all it does — the refusal itself
   * is middleware, so a hidden link and a typed URL get the same answer. This
   * is presentation: a link to a page whose every control returns 403 is a
   * dead end, not a security boundary. */
  protected readonly isPublic = signal(false);

  protected readonly drawerOpen = signal(false);
  protected readonly theme = signal<'light' | 'dark'>(readStoredTheme());

  private readonly url = signal(this.router.url);

  /** The section name shown in the mobile top bar, where there is no sidebar
   * to say which page this is. */
  protected readonly currentLabel = computed(() => {
    const url = this.url().split('?')[0];
    if (url === '/') return 'Overview';
    const all = this.allNav();
    return (
      all.find((item) => item.path !== '/' && url.startsWith(item.path))?.label ?? 'Trading Helper'
    );
  });

  constructor() {
    this.applyTheme(this.theme());
    // Read once at startup: which copy this is, is a property of the container
    // rather than of the session, and cannot change while the page is open.
    // A failure leaves it false, which shows the link — the backend still
    // refuses the write, so the worst case is a dead end rather than a hole.
    void this.settingsService
      .load()
      .then(() => this.isPublic.set(this.settingsService.settings()?.public ?? false))
      .catch(() => this.isPublic.set(false));
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
