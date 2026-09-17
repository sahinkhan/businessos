import { beforeEach, describe, expect, it } from 'vitest';
import { NavigationRegistry } from '../../src/navigation/registry';
import { routeRegistry } from '../../src/navigation/routeRegistry';

describe('navigation registry route references', () => {
  beforeEach(() => routeRegistry.unregister('route_reports'));

  it('rejects unknown route IDs', () => {
    const registry = new NavigationRegistry();
    expect(() =>
      registry.register({ id: 'bad', routeId: 'missing', label: 'Bad', path: '/bad' })
    ).toThrow(/unknown route ID/);
  });

  it('resolves a module navigation contribution from its route ID', () => {
    routeRegistry.register({
      id: 'route_reports',
      moduleOwner: 'reporting',
      path: 'reports',
      component: async () => ({ default: () => null }),
    });
    const registry = new NavigationRegistry();
    registry.register({
      id: 'reports',
      routeId: 'route_reports',
      label: 'Reports',
      path: '/ignored',
    });
    expect(registry.getAll()[0]).toMatchObject({
      routeId: 'route_reports',
      path: '/reports',
    });
  });
});
