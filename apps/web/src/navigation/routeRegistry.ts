import type React from 'react';

export interface RouteContribution {
  id: string;
  path: string;
  owner: string;
  loader: () => Promise<{ default: React.ComponentType }>;
  enabled: boolean;
  permission?: { action: string; resource: string };
  navigation?: { labelKey: string; groupKey: string; icon: string; order: number };
}

type Listener = () => void;
export class RouteRegistry {
  private routes = new Map<string, RouteContribution>();
  private listeners = new Set<Listener>();
  private snapshot: readonly RouteContribution[] = [];

  register(route: RouteContribution) {
    if (
      !route.id.trim() ||
      !route.owner.trim() ||
      !route.path.startsWith('/') ||
      route.path.startsWith('//') ||
      route.path.includes('\\') ||
      !route.loader
    ) {
      throw new Error('Invalid route contribution');
    }
    if (
      this.routes.has(route.id) ||
      [...this.routes.values()].some((item) => item.path === route.path)
    ) {
      throw new Error(`Route contribution collision: ${route.id}`);
    }
    this.routes.set(route.id, route);
    this.publish();
  }
  unregister(id: string) {
    const removed = this.routes.delete(id);
    if (removed) this.publish();
  }
  setEnabled(id: string, enabled: boolean) {
    const route = this.routes.get(id);
    if (route) {
      this.routes.set(id, { ...route, enabled });
      this.publish();
    }
  }
  has(id: string) {
    return this.routes.has(id);
  }
  getAll = () => this.snapshot;
  subscribe = (listener: Listener) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  private publish() {
    this.snapshot = [...this.routes.values()].sort(
      (a, b) =>
        (a.navigation?.order ?? 999) - (b.navigation?.order ?? 999) || a.id.localeCompare(b.id)
    );
    this.listeners.forEach((listener) => listener());
  }
}

export const routeRegistry = new RouteRegistry();
