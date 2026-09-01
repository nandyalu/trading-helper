import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    loadComponent: () => import('./features/overview/overview').then((m) => m.Overview),
  },
  {
    path: 'tickers',
    loadComponent: () => import('./features/tickers/ticker-list').then((m) => m.TickerList),
  },
  {
    path: 'tickers/:ticker',
    loadComponent: () => import('./features/tickers/ticker-detail').then((m) => m.TickerDetailPage),
  },
  {
    path: 'signals',
    loadComponent: () => import('./features/signals/signal-list').then((m) => m.SignalList),
  },
  {
    path: 'signals/:id',
    loadComponent: () => import('./features/signals/signal-detail').then((m) => m.SignalDetailPage),
  },
  {
    path: 'alerts',
    loadComponent: () => import('./features/alerts/alerts-view').then((m) => m.AlertsView),
  },
  {
    path: 'paper',
    loadComponent: () => import('./features/paper/paper-dashboard').then((m) => m.PaperDashboard),
  },
  {
    path: 'agent',
    loadComponent: () => import('./features/agent/agent-view').then((m) => m.AgentView),
  },
  {
    path: 'events',
    loadComponent: () => import('./features/events/events-view').then((m) => m.EventsView),
  },
  {
    path: 'journey',
    loadComponent: () => import('./features/journey/journey-view').then((m) => m.JourneyView),
  },
  {
    path: 'portfolio',
    loadComponent: () =>
      import('./features/portfolio/portfolio-dashboard').then((m) => m.PortfolioDashboard),
  },
  {
    path: 'scorecard',
    loadComponent: () => import('./features/scorecard/scorecard-view').then((m) => m.ScorecardView),
  },
  {
    path: 'digest',
    loadComponent: () => import('./features/digest/digest-view').then((m) => m.DigestView),
  },
  {
    path: 'regime',
    loadComponent: () => import('./features/regime/regime-view').then((m) => m.RegimeView),
  },
  {
    path: 'settings',
    loadComponent: () => import('./features/settings/settings-view').then((m) => m.SettingsView),
  },
];
