import React, { createContext, useContext, useState, useMemo, useCallback } from 'react';
import { NavItem, NavGroup } from './types';
import { navigationRegistry } from './registry';
import { usePermission } from '../permissions/PermissionContext';

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
  const [isSidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [isMobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const { canPerformAction } = usePermission();

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => !prev);
  }, []);

  const groups = useMemo(() => {
    const raw = navigationRegistry.getGroups();
    // Filter items according to permissions
    return raw
      .map((grp) => ({
        ...grp,
        items: grp.items.filter((item) => {
          if (!item.requiredPermission) return true;
          return canPerformAction(item.requiredPermission.action, item.requiredPermission.resource);
        }),
      }))
      .filter((grp) => grp.items.length > 0);
  }, [canPerformAction]);

  const items = useMemo(() => groups.flatMap((g) => g.items), [groups]);

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
  const ctx = useContext(NavigationContext);
  if (!ctx) throw new Error('useNavigation must be used within NavigationProvider');
  return ctx;
};
