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
        labelKey: 'nav.dashboard',
        path: '/',
        icon: 'LayoutDashboard',
        groupKey: 'nav.group.overview',
        order: 1,
      },
      {
        id: 'nav_showcase',
        routeId: 'route_showcase',
        labelKey: 'nav.ui_components',
        path: '/showcase',
        icon: 'Layers',
        groupKey: 'nav.group.foundation_showcase',
        order: 10,
      },
      {
        id: 'nav_datatable',
        routeId: 'route_datatable',
        labelKey: 'nav.datatable_demo',
        path: '/demo/datatable',
        icon: 'Table',
        groupKey: 'nav.group.foundation_showcase',
        order: 11,
      },
      {
        id: 'nav_forms',
        routeId: 'route_forms',
        labelKey: 'nav.forms_inputs',
        path: '/demo/forms',
        icon: 'CheckSquare',
        groupKey: 'nav.group.foundation_showcase',
        order: 12,
      },
      {
        id: 'nav_layouts',
        routeId: 'route_layouts',
        labelKey: 'nav.page_layouts',
        path: '/demo/layouts',
        icon: 'LayoutTemplate',
        groupKey: 'nav.group.foundation_showcase',
        order: 13,
      },
      {
        id: 'nav_settings',
        routeId: 'route_settings',
        labelKey: 'nav.system_settings',
        path: '/settings',
        icon: 'Settings',
        groupKey: 'nav.group.administration',
        order: 99,
      },
    ];
    defaults.forEach((item) => {
      if (!this.items.has(item.id)) this.register(item);
    });
  }

  public register(item: NavItem): void {
    if (!item.id.trim()) throw new Error('Navigation registration failed: invalid identifier.');
    if (!item.labelKey?.trim() && !item.label?.trim()) {
      throw new Error(`Navigation item "${item.id}" requires a translation key or label.`);
    }
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
      const labelKey = item.groupKey ?? 'nav.group.general';
      groupMap.set(labelKey, [...(groupMap.get(labelKey) ?? []), item]);
    }
    return Array.from(groupMap, ([labelKey, items]) => ({
      id: labelKey.replace(/[^a-z0-9]+/gi, '_').toLowerCase(),
      labelKey,
      items,
    }));
  }
}

export const navigationRegistry = new NavigationRegistry(true);
