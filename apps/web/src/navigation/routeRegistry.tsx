import type React from 'react';

export interface ModuleRoutePermissionHint {
  action: string;
  resource: string;
}

export type ModuleRouteScopeRequirement = 'tenant' | 'company' | 'site';

export interface ModuleRouteModule {
  default: React.ComponentType;
}

export interface ModuleRoute {
  id: string;
  path: string;
  moduleOwner: string;
  component: () => Promise<ModuleRouteModule>;
  index?: boolean;
  title?: string;
  requiredPermission?: ModuleRoutePermissionHint;
  requiredCapability?: string;
  requiredScope?: ModuleRouteScopeRequirement;
  errorBoundary?: React.ComponentType<{ children: React.ReactNode }>;
  order?: number;
}

type RegistryListener = () => void;

function normalizePath(path: string): string {
  return path.replace(/^\/+|\/+$/g, '');
}

export class RouteRegistry {
  private readonly routes = new Map<string, ModuleRoute>();
  private readonly listeners = new Set<RegistryListener>();
  private snapshot: readonly ModuleRoute[] = [];

  public register(route: ModuleRoute): void {
    if (!route.id.trim()) throw new Error('Route registration failed: invalid route identifier.');
    if (!route.moduleOwner.trim()) {
      throw new Error(`Route registration failed: route "${route.id}" has no module owner.`);
    }
    if (typeof route.component !== 'function') {
      throw new Error(
        `Route registration failed: route "${route.id}" has no lazy component loader.`
      );
    }
    if (this.routes.has(route.id)) {
      throw new Error(
        `Route registration collision: route ID "${route.id}" is already registered.`
      );
    }

    if (
      route.path.includes('\\') ||
      route.path.startsWith('//') ||
      /^[a-z][a-z0-9+.-]*:/i.test(route.path)
    ) {
      throw new Error(`Route registration failed: route "${route.id}" has an unsafe path.`);
    }
    const path = normalizePath(route.path);
    const isIndex = Boolean(route.index || path === '');
    for (const existing of this.routes.values()) {
      const existingPath = normalizePath(existing.path);
      const existingIsIndex = Boolean(existing.index || existingPath === '');
      if ((isIndex && existingIsIndex) || (!isIndex && !existingIsIndex && path === existingPath)) {
        throw new Error(
          `Route registration collision: path "${route.path}" is already owned by "${existing.id}".`
        );
      }
    }

    this.routes.set(route.id, { ...route, path, index: isIndex });
    this.publish();
  }

  public unregister(id: string): boolean {
    const removed = this.routes.delete(id);
    if (removed) this.publish();
    return removed;
  }

  public get(id: string): ModuleRoute | undefined {
    return this.routes.get(id);
  }

  public has(id: string): boolean {
    return this.routes.has(id);
  }

  public getAll(): readonly ModuleRoute[] {
    return this.snapshot;
  }

  public getPath(id: string): string | null {
    const route = this.routes.get(id);
    if (!route) return null;
    return route.index ? '/' : `/${route.path}`;
  }

  public clear(): void {
    if (this.routes.size === 0) return;
    this.routes.clear();
    this.publish();
  }

  public subscribe = (listener: RegistryListener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  public getSnapshot = (): readonly ModuleRoute[] => this.snapshot;

  private publish(): void {
    this.snapshot = Array.from(this.routes.values()).sort(
      (left, right) =>
        (left.order ?? 50) - (right.order ?? 50) ||
        left.moduleOwner.localeCompare(right.moduleOwner) ||
        left.id.localeCompare(right.id)
    );
    this.listeners.forEach((listener) => listener());
  }
}

export const routeRegistry = new RouteRegistry();
