import React, {
  createContext,
  useContext,
  useState,
  useMemo,
  useCallback,
  useEffect,
  useRef,
} from 'react';
import { apiClient } from '../api/client';
import { securityContext } from '../api/securityContext';
import { useAuth } from '../auth/AuthContext';
import { TenantScope, ActiveScope, ScopeContextValue } from './types';

const EMPTY: ActiveScope = {
  tenantId: '',
  tenantName: '',
  groupId: '',
  groupName: '',
  companyId: '',
  companyName: '',
  siteId: '',
  siteName: '',
};
const ScopeContext = createContext<ScopeContextValue | undefined>(undefined);

function inHierarchy(tenants: TenantScope[], scope: ActiveScope): boolean {
  const tenant = tenants.find((item) => item.id === scope.tenantId);
  const group = tenant?.groups.find((item) => item.id === scope.groupId);
  const company = group?.companies.find((item) => item.id === scope.companyId);
  return Boolean(
    company && (scope.siteId === '' || company.sites.some((item) => item.id === scope.siteId))
  );
}

export const ScopeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { session, refreshToken } = useAuth();
  const [scope, setScopeState] = useState<ActiveScope>(EMPTY);
  const [tenants, setTenants] = useState<TenantScope[]>([]);
  const [isLoading, setLoading] = useState(false);
  const sequence = useRef(0);

  useEffect(() => {
    const version = ++sequence.current;
    setScopeState(EMPTY);
    setTenants([]);
    if (!session) return;
    setLoading(true);
    apiClient
      .get<{ tenants: TenantScope[]; active_scope: ActiveScope }>('/v1/organization/scopes')
      .then((response) => {
        if (version !== sequence.current) return;
        const active = response.active_scope;
        const unselected =
          active?.companyId === '' && session.companyId === null && session.siteId === null;
        if (
          !Array.isArray(response.tenants) ||
          !active ||
          (!unselected && !inHierarchy(response.tenants, active)) ||
          active.tenantId !== session.tenantId ||
          (!unselected &&
            (active.companyId !== session.companyId || active.siteId !== (session.siteId ?? '')))
        ) {
          throw new Error('Invalid authoritative scope');
        }
        setTenants(response.tenants);
        setScopeState(active);
      })
      .catch(() => {
        if (version === sequence.current) {
          setTenants([]);
          setScopeState(EMPTY);
        }
      })
      .finally(() => {
        if (version === sequence.current) setLoading(false);
      });
    return () => {
      sequence.current += 1;
    };
  }, [session]);

  const select = useCallback(
    async (next: ActiveScope) => {
      if (!session || !inHierarchy(tenants, next) || next.tenantId !== session.tenantId) return;
      ++sequence.current;
      setScopeState(EMPTY);
      setTenants([]);
      setLoading(true);
      const current = securityContext.current();
      securityContext.transition(current && { ...current, companyId: null, siteId: null });
      try {
        await apiClient.post('/v1/organization/active-scope', {
          tenant_id: next.tenantId,
          enterprise_group_id: next.groupId,
          company_id: next.companyId,
          operating_site_id: next.siteId,
        });
      } catch {
        // The server remains authoritative; recovery below reloads only a validated session.
      } finally {
        await refreshToken();
        setLoading(false);
      }
    },
    [session, tenants, refreshToken]
  );

  const setTenant = useCallback(
    (id: string) => {
      const tenant = tenants.find((item) => item.id === id);
      const group = tenant?.groups[0];
      const company = group?.companies[0];
      const site = company?.sites[0];
      if (tenant && group && company)
        void select({
          tenantId: tenant.id,
          tenantName: tenant.name,
          groupId: group.id,
          groupName: group.name,
          companyId: company.id,
          companyName: company.name,
          siteId: site?.id ?? '',
          siteName: site?.name ?? '',
        });
    },
    [tenants, select]
  );
  const setCompany = useCallback(
    (id: string) => {
      const tenant = tenants.find((item) => item.id === scope.tenantId);
      for (const group of tenant?.groups ?? []) {
        const company = group.companies.find((item) => item.id === id);
        const site = company?.sites[0];
        if (company) {
          void select({
            ...scope,
            groupId: group.id,
            groupName: group.name,
            companyId: company.id,
            companyName: company.name,
            siteId: site?.id ?? '',
            siteName: site?.name ?? '',
          });
          return;
        }
      }
    },
    [tenants, scope, select]
  );
  const setSite = useCallback(
    (id: string) => {
      const tenant = tenants.find((item) => item.id === scope.tenantId);
      const group = tenant?.groups.find((item) => item.id === scope.groupId);
      const company = group?.companies.find((item) => item.id === scope.companyId);
      const site = company?.sites.find((item) => item.id === id);
      if (site) void select({ ...scope, siteId: site.id, siteName: site.name });
    },
    [tenants, scope, select]
  );
  const setScope = useCallback(
    (partial: Partial<ActiveScope>) => {
      const next = { ...scope, ...partial };
      if (inHierarchy(tenants, next)) void select(next);
    },
    [scope, tenants, select]
  );

  const value = useMemo<ScopeContextValue>(
    () => ({ scope, tenants, isLoading, setTenant, setCompany, setSite, setScope }),
    [scope, tenants, isLoading, setTenant, setCompany, setSite, setScope]
  );
  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
};

export const useScope = (): ScopeContextValue => {
  const context = useContext(ScopeContext);
  if (!context) throw new Error('useScope must be used within ScopeProvider');
  return context;
};
