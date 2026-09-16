import { NavItem, NavGroup } from './types';

class NavigationRegistry {
  private items: Map<string, NavItem> = new Map();

  constructor() {
    this.registerDefaults();
  }

  private registerDefaults() {
    this.register({
      id: 'nav_dashboard',
      label: 'Dashboard',
      path: '/',
      icon: 'LayoutDashboard',
      group: 'Overview',
      order: 1,
    });
    this.register({
      id: 'nav_showcase',
      label: 'UI Components',
      path: '/showcase',
      icon: 'Layers',
      group: 'Foundation Showcase',
      order: 10,
    });
    this.register({
      id: 'nav_datatable',
      label: 'DataTable Demo',
      path: '/demo/datatable',
      icon: 'Table',
      group: 'Foundation Showcase',
      order: 11,
    });
    this.register({
      id: 'nav_forms',
      label: 'Forms & Inputs',
      path: '/demo/forms',
      icon: 'CheckSquare',
      group: 'Foundation Showcase',
      order: 12,
    });
    this.register({
      id: 'nav_layouts',
      label: 'Page Layouts',
      path: '/demo/layouts',
      icon: 'LayoutTemplate',
      group: 'Foundation Showcase',
      order: 13,
    });
    this.register({
      id: 'nav_settings',
      label: 'System Settings',
      path: '/settings',
      icon: 'Settings',
      group: 'Administration',
      order: 99,
    });
  }

  public register(item: NavItem): void {
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
