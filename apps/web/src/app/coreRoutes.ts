import { routeRegistry } from '../navigation/routeRegistry';

const routes = [
  {
    id: 'foundation.dashboard',
    path: '/',
    loader: () =>
      import('../pages/DashboardOverview').then((m) => ({ default: m.DashboardOverview })),
    navigation: {
      labelKey: 'nav.dashboard',
      groupKey: 'nav.overview',
      icon: 'LayoutDashboard',
      order: 1,
    },
  },
  {
    id: 'foundation.showcase',
    path: '/showcase',
    loader: () =>
      import('../pages/ComponentShowcase').then((m) => ({ default: m.ComponentShowcase })),
    navigation: { labelKey: 'nav.showcase', groupKey: 'nav.foundation', icon: 'Layers', order: 10 },
  },
  {
    id: 'foundation.table',
    path: '/demo/datatable',
    loader: () =>
      import('../pages/DataTableDemoPage').then((m) => ({ default: m.DataTableDemoPage })),
    navigation: { labelKey: 'nav.datatable', groupKey: 'nav.foundation', icon: 'Table', order: 11 },
  },
  {
    id: 'foundation.forms',
    path: '/demo/forms',
    loader: () => import('../pages/FormsDemoPage').then((m) => ({ default: m.FormsDemoPage })),
    navigation: {
      labelKey: 'nav.forms',
      groupKey: 'nav.foundation',
      icon: 'CheckSquare',
      order: 12,
    },
  },
  {
    id: 'foundation.layouts',
    path: '/demo/layouts',
    loader: () => import('../pages/LayoutsDemoPage').then((m) => ({ default: m.LayoutsDemoPage })),
    navigation: {
      labelKey: 'nav.layouts',
      groupKey: 'nav.foundation',
      icon: 'LayoutTemplate',
      order: 13,
    },
  },
  {
    id: 'foundation.settings',
    path: '/settings',
    loader: () => import('../pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
    navigation: {
      labelKey: 'nav.settings',
      groupKey: 'nav.administration',
      icon: 'Settings',
      order: 99,
    },
    permission: { action: 'read', resource: 'system.settings' },
  },
] as const;

for (const route of routes) {
  if (!routeRegistry.has(route.id))
    routeRegistry.register({ ...route, owner: 'platform.ui', enabled: true });
}
