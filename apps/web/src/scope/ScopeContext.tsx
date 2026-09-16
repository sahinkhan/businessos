import React, { createContext, useContext, useState, useMemo, useCallback } from 'react';
import { TenantScope, ActiveScope, ScopeContextValue } from './types';

const SCOPE_STORAGE_KEY = 'businessos.active_scope';

const DEFAULT_TENANTS: TenantScope[] = [
  {
    id: 'tenant_global_corp',
    name: 'Global Enterprise Holdings',
    groups: [
      {
        id: 'grp_north_america',
        name: 'North America Group',
        companies: [
          {
            id: 'cmp_us_tech',
            name: 'US Technology Inc',
            code: 'US-TECH',
            currency: 'USD',
            sites: [
              { id: 'site_austin', name: 'Austin Technology Campus', code: 'AUS-01' },
              { id: 'site_seattle', name: 'Seattle HQ Operations', code: 'SEA-01' },
            ],
          },
          {
            id: 'cmp_canada_ops',
            name: 'Canada Logistics Corp',
            code: 'CA-LOG',
            currency: 'CAD',
            sites: [{ id: 'site_toronto', name: 'Toronto Distribution Center', code: 'TOR-01' }],
          },
        ],
      },
      {
        id: 'grp_emea',
        name: 'EMEA Division',
        companies: [
          {
            id: 'cmp_uk_dist',
            name: 'UK Distribution Ltd',
            code: 'UK-DIST',
            currency: 'GBP',
            sites: [{ id: 'site_london', name: 'London Central Hub', code: 'LON-01' }],
          },
        ],
      },
    ],
  },
  {
    id: 'tenant_apac_retail',
    name: 'APAC Retail Ventures',
    groups: [
      {
        id: 'grp_apac_main',
        name: 'APAC Operations Group',
        companies: [
          {
            id: 'cmp_singapore',
            name: 'Singapore Trading Pte Ltd',
            code: 'SG-TRD',
            currency: 'SGD',
            sites: [{ id: 'site_sg_port', name: 'Jurong Logistics Depot', code: 'SG-01' }],
          },
        ],
      },
    ],
  },
];

const ScopeContext = createContext<ScopeContextValue | undefined>(undefined);

export const ScopeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const tenants = DEFAULT_TENANTS;

  const [scope, setScopeState] = useState<ActiveScope>(() => {
    try {
      const stored = localStorage.getItem(SCOPE_STORAGE_KEY);
      if (stored) return JSON.parse(stored);
    } catch {
      // ignore
    }
    const t = DEFAULT_TENANTS[0];
    const g = t.groups[0];
    const c = g.companies[0];
    const s = c.sites[0];
    return {
      tenantId: t.id,
      tenantName: t.name,
      groupId: g.id,
      groupName: g.name,
      companyId: c.id,
      companyName: c.name,
      siteId: s.id,
      siteName: s.name,
    };
  });

  const saveScope = useCallback((newScope: ActiveScope) => {
    setScopeState(newScope);
    try {
      localStorage.setItem(SCOPE_STORAGE_KEY, JSON.stringify(newScope));
    } catch {
      // ignore
    }
  }, []);

  const setTenant = useCallback(
    (tenantId: string) => {
      const t = tenants.find((item) => item.id === tenantId);
      if (!t) return;
      const g = t.groups[0];
      const c = g.companies[0];
      const s = c.sites[0];
      saveScope({
        tenantId: t.id,
        tenantName: t.name,
        groupId: g.id,
        groupName: g.name,
        companyId: c.id,
        companyName: c.name,
        siteId: s.id,
        siteName: s.name,
      });
    },
    [tenants, saveScope]
  );

  const setCompany = useCallback(
    (companyId: string) => {
      const t = tenants.find((item) => item.id === scope.tenantId);
      if (!t) return;
      for (const g of t.groups) {
        const c = g.companies.find((comp) => comp.id === companyId);
        if (c) {
          const s = c.sites[0];
          saveScope({
            ...scope,
            groupId: g.id,
            groupName: g.name,
            companyId: c.id,
            companyName: c.name,
            siteId: s.id,
            siteName: s.name,
          });
          return;
        }
      }
    },
    [tenants, scope, saveScope]
  );

  const setSite = useCallback(
    (siteId: string) => {
      const t = tenants.find((item) => item.id === scope.tenantId);
      if (!t) return;
      for (const g of t.groups) {
        for (const c of g.companies) {
          const s = c.sites.find((st) => st.id === siteId);
          if (s) {
            saveScope({
              ...scope,
              groupId: g.id,
              groupName: g.name,
              companyId: c.id,
              companyName: c.name,
              siteId: s.id,
              siteName: s.name,
            });
            return;
          }
        }
      }
    },
    [tenants, scope, saveScope]
  );

  const setScope = useCallback(
    (partial: Partial<ActiveScope>) => {
      saveScope({ ...scope, ...partial });
    },
    [scope, saveScope]
  );

  const value = useMemo(
    () => ({
      scope,
      tenants,
      setTenant,
      setCompany,
      setSite,
      setScope,
    }),
    [scope, tenants, setTenant, setCompany, setSite, setScope]
  );

  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
};

export const useScope = (): ScopeContextValue => {
  const ctx = useContext(ScopeContext);
  if (!ctx) throw new Error('useScope must be used within ScopeProvider');
  return ctx;
};
