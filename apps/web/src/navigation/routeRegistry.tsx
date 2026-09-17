import React from 'react';
import { DashboardOverview } from '../pages/DashboardOverview';
import { ComponentShowcase } from '../pages/ComponentShowcase';
import { DataTableDemoPage } from '../pages/DataTableDemoPage';
import { FormsDemoPage } from '../pages/FormsDemoPage';
import { LayoutsDemoPage } from '../pages/LayoutsDemoPage';
import { SettingsPage } from '../pages/SettingsPage';
import { ForbiddenPage } from '../pages/states/ForbiddenPage';

export interface ModuleRoutePermissionHint {
  action: string;
  resource: string;
}

export interface ModuleRoute {
  /** Stable unique route identifier */
  id: string;
  /** Route path relative to shell (e.g. '' for index, 'showcase', 'demo/datatable') */
  path: string;
  /** Optional module owner identifier (e.g. 'foundation', 'sales', 'inventory') */
  moduleOwner?: string;
  /** React element to render */
  element: React.ReactElement;
  /** Optional flag indicating an index route */
  index?: boolean;
  /** Optional human-readable title or translation key */
  title?: string;
  /** Optional Phase 4 policy presentation hint */
  requiredPermission?: ModuleRoutePermissionHint;
  /** Optional capability hint */
  requiredCapability?: string;
  /** Optional route-level error boundary component */
  errorBoundary?: React.ComponentType<{ children?: React.ReactNode; error?: Error }>;
  /** Optional sort/display order */
  order?: number;
}

export class RouteRegistry {
  private routes: Map<string, ModuleRoute> = new Map();

  constructor() {
    this.registerDefaults();
  }

  public registerDefaults(): void {
    this.register({
      id: 'route_dashboard',
      path: '',
      index: true,
      element: <DashboardOverview />,
      title: 'Dashboard',
      order: 1,
    });

    this.register({
      id: 'route_showcase',
      moduleOwner: 'foundation',
      path: 'showcase',
      element: <ComponentShowcase />,
      title: 'UI Components',
      order: 10,
    });

    this.register({
      id: 'route_datatable',
      moduleOwner: 'foundation',
      path: 'demo/datatable',
      element: <DataTableDemoPage />,
      title: 'DataTable Demo',
      order: 11,
    });

    this.register({
      id: 'route_forms',
      moduleOwner: 'foundation',
      path: 'demo/forms',
      element: <FormsDemoPage />,
      title: 'Forms & Inputs',
      order: 12,
    });

    this.register({
      id: 'route_layouts',
      moduleOwner: 'foundation',
      path: 'demo/layouts',
      element: <LayoutsDemoPage />,
      title: 'Page Layouts',
      order: 13,
    });

    this.register({
      id: 'route_settings',
      moduleOwner: 'foundation',
      path: 'settings',
      element: <SettingsPage />,
      title: 'System Settings',
      order: 99,
    });

    this.register({
      id: 'route_forbidden',
      moduleOwner: 'foundation',
      path: 'forbidden',
      element: <ForbiddenPage />,
      title: 'Forbidden',
      order: 100,
    });
  }

  /**
   * Registers a module route contribution with collision detection.
   */
  public register(route: ModuleRoute): void {
    if (!route.id || typeof route.id !== 'string') {
      throw new Error('Route registration failed: Invalid route identifier.');
    }

    if (this.routes.has(route.id)) {
      throw new Error(
        `Route registration collision: Route ID "${route.id}" is already registered.`
      );
    }

    // Path collision detection
    const normalizedPath = route.path ? route.path.replace(/^\/+|\/+$/g, '') : '';
    const isIndex = Boolean(route.index || normalizedPath === '');

    for (const existing of this.routes.values()) {
      const existingNormalized = existing.path ? existing.path.replace(/^\/+|\/+$/g, '') : '';
      const existingIsIndex = Boolean(existing.index || existingNormalized === '');

      if (isIndex && existingIsIndex) {
        throw new Error(
          `Route collision: An index route is already registered by "${existing.id}". Cannot register duplicate index route "${route.id}".`
        );
      }

      if (!isIndex && !existingIsIndex && normalizedPath === existingNormalized) {
        throw new Error(
          `Route collision: Path "${route.path}" is already registered by "${existing.id}". Cannot register duplicate route "${route.id}".`
        );
      }
    }

    this.routes.set(route.id, route);
  }

  public unregister(id: string): boolean {
    return this.routes.delete(id);
  }

  public get(id: string): ModuleRoute | undefined {
    return this.routes.get(id);
  }

  public has(id: string): boolean {
    return this.routes.has(id);
  }

  public getAll(): ModuleRoute[] {
    return Array.from(this.routes.values()).sort((a, b) => (a.order ?? 50) - (b.order ?? 50));
  }

  public clear(): void {
    this.routes.clear();
  }
}

export const routeRegistry = new RouteRegistry();
