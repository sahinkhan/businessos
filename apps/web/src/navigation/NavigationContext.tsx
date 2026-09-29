import React, {
  createContext,
  useContext,
  useState,
  useMemo,
  useCallback,
  useEffect,
  useSyncExternalStore,
} from 'react';
import '../app/coreRoutes';
import { NavItem, NavGroup } from './types';
import { routeRegistry } from './routeRegistry';
import { usePermission } from '../permissions/PermissionContext';
import { useI18n } from '../i18n/I18nContext';

export interface NavigationContextValue {
  items: NavItem[];
  groups: NavGroup[];
  isSidebarCollapsed: boolean;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  isMobileDrawerOpen: boolean;
  setMobileDrawerOpen: (open: boolean) => void;
}

const NavigationContext = createContext<NavigationContextValue | undefined>(undefined);

export const NavigationProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const routes = useSyncExternalStore(routeRegistry.subscribe, routeRegistry.getAll);
  const [isSidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [isMobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const { canPerformAction, loadAction } = usePermission();
  const { t } = useI18n();

  useEffect(() => {
    for (const route of routes) {
      if (route.enabled && route.navigation && route.permission)
        void loadAction(route.permission.action, route.permission.resource);
    }
  }, [routes, loadAction]);

  const toggleSidebar = useCallback(() => setSidebarCollapsed((previous) => !previous), []);
  const items = useMemo<NavItem[]>(
    () =>
      routes
        .filter(
          (route) =>
            route.enabled &&
            route.navigation &&
            (!route.permission ||
              canPerformAction(route.permission.action, route.permission.resource))
        )
        .map((route) => ({
          id: route.id,
          label: t(route.navigation!.labelKey),
          path: route.path,
          icon: route.navigation!.icon,
          group: t(route.navigation!.groupKey),
          order: route.navigation!.order,
          requiredPermission: route.permission,
        })),
    [routes, canPerformAction, t]
  );
  const groups = useMemo<NavGroup[]>(() => {
    const grouped = new Map<string, NavItem[]>();
    for (const item of items) {
      const label = item.group ?? '';
      grouped.set(label, [...(grouped.get(label) ?? []), item]);
    }
    return [...grouped.entries()].map(([label, entries]) => ({ id: label, label, items: entries }));
  }, [items]);
  const value = useMemo(
    () => ({
      items,
      groups,
      isSidebarCollapsed,
      toggleSidebar,
      setSidebarCollapsed,
      isMobileDrawerOpen,
      setMobileDrawerOpen,
    }),
    [items, groups, isSidebarCollapsed, toggleSidebar, isMobileDrawerOpen]
  );
  return <NavigationContext.Provider value={value}>{children}</NavigationContext.Provider>;
};

export const useNavigation = (): NavigationContextValue => {
  const context = useContext(NavigationContext);
  if (!context) throw new Error('useNavigation must be used within NavigationProvider');
  return context;
};
