import { routeRegistry, ModuleRoute } from '../navigation/routeRegistry';

const coreRoutes: ModuleRoute[] = [
  {
    id: 'route_dashboard',
    moduleOwner: 'ui.foundation',
    path: '',
    index: true,
    component: () =>
      import('../pages/DashboardOverview').then(({ DashboardOverview }) => ({
        default: DashboardOverview,
      })),
    title: 'Dashboard',
    requiredScope: 'site',
    order: 1,
  },
  {
    id: 'route_showcase',
    moduleOwner: 'ui.foundation',
    path: 'showcase',
    component: () =>
      import('../pages/ComponentShowcase').then(({ ComponentShowcase }) => ({
        default: ComponentShowcase,
      })),
    title: 'UI Components',
    order: 10,
  },
  {
    id: 'route_datatable',
    moduleOwner: 'ui.foundation',
    path: 'demo/datatable',
    component: () =>
      import('../pages/DataTableDemoPage').then(({ DataTableDemoPage }) => ({
        default: DataTableDemoPage,
      })),
    title: 'DataTable Demo',
    order: 11,
  },
  {
    id: 'route_forms',
    moduleOwner: 'ui.foundation',
    path: 'demo/forms',
    component: () =>
      import('../pages/FormsDemoPage').then(({ FormsDemoPage }) => ({
        default: FormsDemoPage,
      })),
    title: 'Forms & Inputs',
    order: 12,
  },
  {
    id: 'route_layouts',
    moduleOwner: 'ui.foundation',
    path: 'demo/layouts',
    component: () =>
      import('../pages/LayoutsDemoPage').then(({ LayoutsDemoPage }) => ({
        default: LayoutsDemoPage,
      })),
    title: 'Page Layouts',
    order: 13,
  },
  {
    id: 'route_settings',
    moduleOwner: 'ui.foundation',
    path: 'settings',
    component: () =>
      import('../pages/SettingsPage').then(({ SettingsPage }) => ({ default: SettingsPage })),
    title: 'System Settings',
    order: 99,
  },
  {
    id: 'route_forbidden',
    moduleOwner: 'ui.foundation',
    path: 'forbidden',
    component: () => import('../pages/states/ForbiddenRoutePage'),
    title: 'Forbidden',
    order: 100,
  },
];

export function registerCoreRouteContributions(): void {
  for (const route of coreRoutes) {
    if (!routeRegistry.has(route.id)) routeRegistry.register(route);
  }
}

registerCoreRouteContributions();
