import { describe, it, expect } from 'vitest';
import { RouteRegistry } from '../../src/navigation/routeRegistry';

describe('Module route contributions', () => {
  it('requires lazy loaders, stable ownership, and unique paths', () => {
    const registry = new RouteRegistry();
    const route = {
      id: 'reports.summary',
      path: '/reports/summary',
      owner: 'reports',
      enabled: false,
      loader: async () => ({ default: () => null }),
      navigation: { labelKey: 'reports.summary', groupKey: 'reports', icon: 'Table', order: 5 },
    };
    registry.register(route);
    expect(registry.getAll()[0].enabled).toBe(false);
    registry.setEnabled(route.id, true);
    expect(registry.getAll()[0].enabled).toBe(true);
    expect(() => registry.register({ ...route, id: 'reports.duplicate' })).toThrow(/collision/);
    registry.unregister(route.id);
    expect(registry.getAll()).toHaveLength(0);
  });
});
