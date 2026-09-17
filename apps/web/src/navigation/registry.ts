import { NavItem, NavGroup } from './types';
import { routeRegistry } from './routeRegistry';

export class NavigationRegistry {
  private items: Map<string, NavItem> = new Map();

  constructor() {
    this.registerDefaults();
  }

  public registerDefaults(): void {
    this.register({
      id: 'nav_dashboard',
      routeId: 'route_dashboard',
      label: 'Dashboard',
      path: '/',
      icon: 'LayoutDashboard',
      group: 'Overview',
      order: 1,
    });

    this.register({
      id: 'nav_showcase',
      routeId: 'route_showcase',
      label: 'UI Components',
      path: '/showcase',
      icon: 'Layers',
      group: 'Foundation Showcase',
      order: 10,
    });

    this.register({
      id: 'nav_datatable',
      routeId: 'route_datatable',
      label: 'DataTable Demo',
      path: '/demo/datatable',
      icon: 'Table',
      group: 'Foundation Showcase',
      order: 11,
    });

    this.register({
      id: 'nav_forms',
      routeId: 'route_forms',
      label: 'Forms & Inputs',
      path: '/demo/forms',
      icon: 'CheckSquare',
      group: 'Foundation Showcase',
      order: 12,
    });

    this.register({
      id: 'nav_layouts',
      routeId: 'route_layouts',
      label: 'Page Layouts',
      path: '/demo/layouts',
      icon: 'LayoutTemplate',
      group: 'Foundation Showcase',
      order: 13,
    });

    this.register({
      id: 'nav_settings',
      routeId: 'route_settings',
      label: 'System Settings',
      path: '/settings',
      icon: 'Settings',
      group: 'Administration',
      order: 99,
    });
  }

  public register(item: NavItem): void {
    if (!item.id || typeof item.id !== 'string') {
      throw new Error('Navigation registration failed: Invalid identifier.');
    }

    // Verify item references a valid route in RouteRegistry
    if (item.routeId) {
      if (!routeRegistry.has(item.routeId)) {
        throw new Error(`Navigation item "${item.id}" targets unknown route ID "${item.routeId}".`);
      }
      const route = routeRegistry.get(item.routeId);
      if (route) {
        if (!item.path) {
          item.path = route.index ? '/' : `/${route.path.replace(/^\/+/, '')}`;
        }
        if (route.requiredPermission && !item.requiredPermission) {
          item.requiredPermission = route.requiredPermission;
        }
      }
    } else {
      // If routeId is omitted, check if path corresponds to a registered route
      const cleanPath = item.path ? item.path.replace(/^\/+|\/+$/g, '') : '';
      const matchingRoute = routeRegistry.getAll().find((r) => {
        const rPath = r.path ? r.path.replace(/^\/+|\/+$/g, '') : '';
        if (r.index || rPath === '') {
          return cleanPath === '';
        }
        return rPath === cleanPath;
      });

      if (!matchingRoute) {
        throw new Error(
          `Navigation item "${item.id}" targets unknown route path "${item.path}". Navigation cannot target an unknown route.`
        );
      }

      item.routeId = matchingRoute.id;
      if (matchingRoute.requiredPermission && !item.requiredPermission) {
        item.requiredPermission = matchingRoute.requiredPermission;
      }
    }

    this.items.set(item.id, item);
  }

  public unregister(id: string): void {
    this.items.delete(id);
  }

  public getAll(): NavItem[] {
    return Array.from(this.items.values()).sort((a, b) => (a.order ?? 50) - (b.order ?? 50));
  }

  public getGroups(): NavGroup[] {
    const groupMap = new Map<string, NavItem[]>();
    const all = this.getAll();

    all.forEach((item) => {
      const g = item.group || 'General';
      if (!groupMap.has(g)) {
        groupMap.set(g, []);
      }
      groupMap.get(g)!.push(item);
    });

    const groups: NavGroup[] = [];
    groupMap.forEach((items, label) => {
      groups.push({
        id: label.toLowerCase().replace(/\s+/g, '_'),
        label,
        items,
      });
    });

    return groups;
  }
}

export const navigationRegistry = new NavigationRegistry();
