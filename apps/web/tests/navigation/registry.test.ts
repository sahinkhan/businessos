import { describe, it, expect, beforeEach } from 'vitest';
import { navigationRegistry } from '../../src/navigation/registry';
import { routeRegistry } from '../../src/navigation/routeRegistry';

describe('Navigation Registry', () => {
  beforeEach(() => {
    navigationRegistry.unregister('custom_reports');
    routeRegistry.unregister('route_custom_reports');
  });

  it('rejects navigation items targeting an unknown route ID', () => {
    expect(() => {
      navigationRegistry.register({
        id: 'bad_nav_item',
        routeId: 'non_existent_route_id',
        label: 'Bad Nav',
        path: '/bad/path',
      });
    }).toThrow(/targets unknown route ID/);
  });

  it('rejects navigation items targeting an unknown route path without route ID', () => {
    expect(() => {
      navigationRegistry.register({
        id: 'bad_nav_item_2',
        label: 'Bad Nav 2',
        path: '/unregistered/route/path',
      });
    }).toThrow(/targets unknown route/);
  });

  it('registers navigation items dynamically when route is registered and groups them', () => {
    routeRegistry.register({
      id: 'route_custom_reports',
      moduleOwner: 'finance',
      path: 'reports/financial',
      element: { type: 'div', props: { children: 'Financial Statements' }, key: null },
      title: 'Financial Statements',
    });

    navigationRegistry.register({
      id: 'custom_reports',
      routeId: 'route_custom_reports',
      label: 'Financial Statements',
      path: '/reports/financial',
      group: 'Reporting',
      order: 5,
    });

    const items = navigationRegistry.getAll();
    const registered = items.find((i) => i.id === 'custom_reports');
    expect(registered).toBeDefined();
    expect(registered?.label).toBe('Financial Statements');
    expect(registered?.routeId).toBe('route_custom_reports');

    const groups = navigationRegistry.getGroups();
    const reportGroup = groups.find((g) => g.label === 'Reporting');
    expect(reportGroup).toBeDefined();
    expect(reportGroup?.items.some((i) => i.id === 'custom_reports')).toBe(true);

    navigationRegistry.unregister('custom_reports');
    routeRegistry.unregister('route_custom_reports');
  });
});
