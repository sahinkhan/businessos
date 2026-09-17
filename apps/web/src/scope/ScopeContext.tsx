import React, { createContext, useContext, useState, useMemo, useCallback, useEffect } from 'react';
import { TenantScope, ActiveScope, ScopeContextValue } from './types';
import { ScopeAdapter, defaultScopeAdapter, CONTRACT_DEFAULT_TENANTS } from './scopeAdapter';
import { apiClient } from '../api/client';
import { queryCache } from '../api/queryCache';

const SCOPE_STORAGE_KEY = 'businessos.active_scope';

const ScopeContext = createContext<ScopeContextValue | undefined>(undefined);

export interface ScopeProviderProps {
  children: React.ReactNode;
  adapter?: ScopeAdapter;
  initialTenants?: TenantScope[];
}

export const ScopeProvider: React.FC<ScopeProviderProps> = ({
  children,
  adapter = defaultScopeAdapter,
  initialTenants = CONTRACT_DEFAULT_TENANTS,
}) => {
  const [tenants, setTenants] = useState<TenantScope[]>(initialTenants);

  // Load backend-authoritative tenants
  useEffect(() => {
    let isMounted = true;
    adapter
      .fetchTenants()
      .then((loaded) => {
        if (isMounted && loaded && loaded.length > 0) {
          setTenants(loaded);
        }
      })
      .catch(() => {
        // Fallback to initialTenants if backend is unavailable
      });
    return () => {
      isMounted = false;
    };
  }, [adapter]);

  const [scope, setScopeState] = useState<ActiveScope>(() => {
    try {
      const stored = localStorage.getItem(SCOPE_STORAGE_KEY);
      if (stored) return JSON.parse(stored);
    } catch {
      // ignore
    }
    const t = initialTenants[0];
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

  // Wire ApiClient active scope header provider
  useEffect(() => {
    apiClient.setScopeProvider(() => ({
      tenantId: scope.tenantId,
      companyId: scope.companyId,
      siteId: scope.siteId,
    }));
  }, [scope]);

  // Validate stored scope on load; if stale or invalid, fail safely and reset
  useEffect(() => {
    adapter.validateScope(scope).then((isValid) => {
      if (!isValid && tenants.length > 0) {
        const t = tenants[0];
        const g = t.groups[0];
        const c = g.companies[0];
        const s = c.sites[0];
        const fallbackScope: ActiveScope = {
          tenantId: t.id,
          tenantName: t.name,
          groupId: g.id,
          groupName: g.name,
          companyId: c.id,
          companyName: c.name,
          siteId: s.id,
          siteName: s.name,
        };
        setScopeState(fallbackScope);
        localStorage.setItem(SCOPE_STORAGE_KEY, JSON.stringify(fallbackScope));
        queryCache.clear();
      }
    });
  }, [adapter, tenants, scope]);

  const applyValidatedScope = useCallback((newScope: ActiveScope) => {
    setScopeState(newScope);
    try {
      localStorage.setItem(SCOPE_STORAGE_KEY, JSON.stringify(newScope));
    } catch {
      // ignore
    }
    // Purge query cache on scope transition to prevent cross-scope/cross-tenant data leakage
    queryCache.clear();
  }, []);

  const setTenant = useCallback(
    (tenantId: string) => {
      adapter
        .selectActiveScope({ tenant_id: tenantId })
        .then((result) => {
          if (result.valid) {
            applyValidatedScope(result.scope);
          }
        })
        .catch(() => {
          // Fail safely on error
        });
    },
    [adapter, applyValidatedScope]
  );

  const setCompany = useCallback(
    (companyId: string) => {
      adapter
        .selectActiveScope({ tenant_id: scope.tenantId, company_id: companyId })
        .then((result) => {
          if (result.valid) {
            applyValidatedScope(result.scope);
          }
        })
        .catch(() => {
          // Fail safely on error
        });
    },
    [adapter, scope.tenantId, applyValidatedScope]
  );

  const setSite = useCallback(
    (siteId: string) => {
      adapter
        .selectActiveScope({
          tenant_id: scope.tenantId,
          company_id: scope.companyId,
          operating_site_id: siteId,
        })
        .then((result) => {
          if (result.valid) {
            applyValidatedScope(result.scope);
          }
        })
        .catch(() => {
          // Fail safely on error
        });
    },
    [adapter, scope.tenantId, scope.companyId, applyValidatedScope]
  );

  const setScope = useCallback(
    (partial: Partial<ActiveScope>) => {
      const selection = {
        tenant_id: partial.tenantId || scope.tenantId,
        company_id: partial.companyId || scope.companyId,
        operating_site_id: partial.siteId || scope.siteId,
      };
      adapter
        .selectActiveScope(selection)
        .then((result) => {
          if (result.valid) {
            applyValidatedScope(result.scope);
          }
        })
        .catch(() => {
          // Fail safely
        });
    },
    [adapter, scope, applyValidatedScope]
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
