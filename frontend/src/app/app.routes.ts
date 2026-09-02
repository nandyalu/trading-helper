import { Routes } from '@angular/router';

/**
 * Eight routes, each answering one question a reader would actually ask.
 *
 * This is a site about an experiment, not a console for running one. The old
 * route table had twelve entries shaped like an operator's tools — a page per
 * data source, with Tickers, Signals, Alerts, Regime and Digest each standing
 * alone. A reader does not arrive wanting "the alerts table"; they arrive
 * wanting to know what the agent did and whether it worked.
 *
 * So: what is this (`/`), what did it do with the money (`/book`), why did it
 * do that (`/decisions`), what did it read (`/research`), is it any good
 * (`/scorecard`), and what have we changed (`/journal`).
 *
 * Alerts, the regime line and the weekly digest did not get their own pages.
 * Each is context for something else and now sits inside it — the regime in
 * the hero and on each decision, the alerts on a ticker's timeline, the digest
 * in the journal.
 */
export const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./features/experiment/experiment-view').then((m) => m.ExperimentView),
    pathMatch: 'full',
  },
  {
    path: 'book',
    loadComponent: () => import('./features/book/book-view').then((m) => m.BookView),
  },
  {
    path: 'decisions',
    loadComponent: () => import('./features/decisions/decisions-view').then((m) => m.DecisionsView),
  },
  {
    path: 'research',
    loadComponent: () => import('./features/research/research-view').then((m) => m.ResearchView),
  },
  // Ticker and analysis detail live under /research because that is what they
  // are: one name it studied, and one study of it.
  {
    path: 'research/ticker/:ticker',
    loadComponent: () =>
      import('./features/research/ticker-detail').then((m) => m.TickerDetailPage),
  },
  {
    path: 'research/analysis/:id',
    loadComponent: () =>
      import('./features/research/signal-detail').then((m) => m.SignalDetailPage),
  },
  {
    path: 'idea',
    loadComponent: () => import('./features/idea/idea-view').then((m) => m.IdeaView),
  },
  {
    path: 'scorecard',
    loadComponent: () => import('./features/scorecard/scorecard-view').then((m) => m.ScorecardView),
  },
  {
    path: 'journal',
    loadComponent: () => import('./features/journal/journal-view').then((m) => m.JournalView),
  },
  // The design system on real content. Kept out of the nav: it is a working
  // surface, not a page anyone should land on.
  {
    path: 'preview',
    loadComponent: () => import('./features/preview/preview-view').then((m) => m.PreviewView),
  },
  {
    path: 'settings',
    loadComponent: () => import('./features/settings/settings-view').then((m) => m.SettingsView),
  },
  // The old paths, kept as redirects. Links to them exist in Discord posts, in
  // the journal, and in anything anyone has bookmarked; a rename that breaks
  // them loses the trail back to what was being discussed.
  { path: 'agent', redirectTo: 'book' },
  { path: 'events', redirectTo: 'decisions' },
  { path: 'journey', redirectTo: 'journal' },
  { path: 'tickers', redirectTo: 'research' },
  { path: 'signals', redirectTo: 'research' },
  { path: 'tickers/:ticker', redirectTo: 'research/ticker/:ticker' },
  { path: 'signals/:id', redirectTo: 'research/analysis/:id' },
  { path: 'alerts', redirectTo: 'book' },
  { path: 'regime', redirectTo: '' },
  { path: 'digest', redirectTo: 'journal' },
  { path: '**', redirectTo: '' },
];
