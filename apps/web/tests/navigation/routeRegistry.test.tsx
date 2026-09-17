import { describe, it, expect, beforeEach } from 'vitest';
import { RouteRegistry } from '../../src/navigation/routeRegistry';

describe('RouteRegistry Module Contribution', () => {
  let registry: RouteRegistry;

  beforeEach(() => {
    registry = new RouteRegistry();
  });

  it('initializes with default core foundation routes', () => {
    const routes = registry.getAll();
    expect(routes.length).toBeGreaterThanOrEqual(6);
    expect(routes.some((r) => r.id === 'route_dashboard' && r.index)).toBe(true);
    expect(routes.some((r) => r.id === 'route_showcase' && r.path === 'showcase')).toBe(true);
    expect(routes.some((r) => r.id === 'route_settings' && r.path === 'settings')).toBe(true);
  });

  it('allows modules to register custom routes and sorts them by order', () => {
    registry.register({
      id: 'module_ledger',
      path: 'finance/ledger',
      element: <div>General Ledger</div>,
      title: 'General Ledger',
      order: 20,
    });

    expect(registry.has('module_ledger')).toBe(true);
    const route = registry.get('module_ledger');
    expect(route?.title).toBe('General Ledger');

    const all = registry.getAll();
    const index = all.findIndex((r) => r.id === 'module_ledger');
    expect(index).toBeGreaterThan(0);
    // Should be after dashboard (order 1) and showcase (order 10)
    expect(all[index].order).toBe(20);
  });

  it('detects and rejects duplicate route identifier collision', () => {
    expect(() => {
      registry.register({
        id: 'route_dashboard',
        path: 'another-dashboard',
        element: <div>Duplicate ID</div>,
      });
    }).toThrow(/Route registration collision/);
  });

  it('detects and rejects duplicate index route collision', () => {
    expect(() => {
      registry.register({
        id: 'another_root',
        path: '',
        index: true,
        element: <div>Another Root</div>,
      });
    }).toThrow(/Route collision: An index route is already registered/);
  });

  it('detects and rejects duplicate route path collision', () => {
    expect(() => {
      registry.register({
        id: 'duplicate_showcase_path',
        path: 'showcase',
        element: <div>Duplicate Showcase</div>,
      });
    }).toThrow(/Route collision: Path "showcase" is already registered/);
  });

  it('allows unregistering a module route', () => {
    registry.register({
      id: 'temporary_module',
      path: 'temp/route',
      element: <div>Temp</div>,
    });

    expect(registry.has('temporary_module')).toBe(true);
    const removed = registry.unregister('temporary_module');
    expect(removed).toBe(true);
    expect(registry.has('temporary_module')).toBe(false);
  });
});
