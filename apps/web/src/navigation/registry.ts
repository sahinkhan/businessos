import '../app/coreRouteContributions';
import { NavItem, NavGroup } from './types';
import { routeRegistry } from './routeRegistry';

export class NavigationRegistry {
  private readonly items = new Map<string, NavItem>();

  constructor(registerDefaults = false) {
    if (registerDefaults) this.registerDefaults();
  }

  public registerDefaults(): void {
    const defaults: NavItem[] = [
      {
        id: 'nav_dashboard',
        routeId: 'route_dashboard',
        label: 'Dashboard',
        path: '/',
        icon: 'LayoutDashboard',
        group: 'Overview',
        order: 1,
      },
      {
        id: 'nav_showcase',
        routeId: 'route_showcase',
        label: 'UI Components',
        path: '/showcase',
        icon: 'Layers',
        group: 'Foundation Showcase',
        order: 10,
      },
      {
        id: 'nav_datatable',
        routeId: 'route_datatable',
        label: 'DataTable Demo',
        path: '/demo/datatable',
        icon: 'Table',
        group: 'Foundation Showcase',
        order: 11,
      },
      {
        id: 'nav_forms',
        routeId: 'route_forms',
        label: 'Forms & Inputs',
        path: '/demo/forms',
        icon: 'CheckSquare',
        group: 'Foundation Showcase',
        order: 12,
      },
      {
        id: 'nav_layouts',
        routeId: 'route_layouts',
        label: 'Page Layouts',
        path: '/demo/layouts',
        icon: 'LayoutTemplate',
        group: 'Foundation Showcase',
        order: 13,
      },
      {
        id: 'nav_settings',
        routeId: 'route_settings',
        label: 'System Settings',
        path: '/settings',
        icon: 'Settings',
        group: 'Administration',
        order: 99,
      },
    ];
    defaults.forEach((item) => {
      if (!this.items.has(item.id)) this.register(item);
    });
  }

  public register(item: NavItem): void {
    if (!item.id.trim()) throw new Error('Navigation registration failed: invalid identifier.');
    if (this.items.has(item.id)) {
      throw new Error(`Navigation registration collision: item ID "${item.id}" already exists.`);
    }
    if (!item.routeId || !routeRegistry.has(item.routeId)) {
      throw new Error(
        `Navigation item "${item.id}" targets unknown route ID "${item.routeId ?? ''}".`
      );
    }

    const route = routeRegistry.get(item.routeId)!;
    const path = routeRegistry.getPath(item.routeId)!;
    this.items.set(item.id, {
      ...item,
      path,
      requiredPermission: item.requiredPermission ?? route.requiredPermission,
    });
  }

  public unregister(id: string): boolean {
    return this.items.delete(id);
  }

  public getAll(): NavItem[] {
    return Array.from(this.items.values()).sort(
      (left, right) => (left.order ?? 50) - (right.order ?? 50) || left.id.localeCompare(right.id)
    );
  }

  public getGroups(): NavGroup[] {
    const groupMap = new Map<string, NavItem[]>();
    for (const item of this.getAll()) {
      const label = item.group || 'General';
      groupMap.set(label, [...(groupMap.get(label) ?? []), item]);
    }
    return Array.from(groupMap, ([label, items]) => ({
      id: label.toLowerCase().replace(/\s+/g, '_'),
      label,
      items,
    }));
  }
}

export const navigationRegistry = new NavigationRegistry(true);
