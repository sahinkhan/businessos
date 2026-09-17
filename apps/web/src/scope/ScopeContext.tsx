import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../api/client';
import { queryCache } from '../api/queryCache';
import { useAuth } from '../auth/AuthContext';
import { ActiveScopeSelection, ScopeAdapter, defaultScopeAdapter } from './scopeAdapter';
import { ActiveScope, ScopeContextValue, ScopeStatus, TenantScope } from './types';

const ScopeContext = createContext<ScopeContextValue | undefined>(undefined);
const SCOPE_PREFERENCE_KEY = 'businessos.scope.preference';

interface ScopePreference {
  tenant_id: string;
  legal_entity_id?: string;
  company_id?: string;
  operating_site_id?: string;
}

function readPreference(): ScopePreference | null {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(SCOPE_PREFERENCE_KEY) ?? 'null');
    if (typeof value !== 'object' || value === null) return null;
    const candidate = value as Record<string, unknown>;
    if (typeof candidate.tenant_id !== 'string') return null;
    return {
      tenant_id: candidate.tenant_id,
      legal_entity_id:
        typeof candidate.legal_entity_id === 'string' ? candidate.legal_entity_id : undefined,
      company_id: typeof candidate.company_id === 'string' ? candidate.company_id : undefined,
      operating_site_id:
        typeof candidate.operating_site_id === 'string' ? candidate.operating_site_id : undefined,
    };
  } catch {
    return null;
  }
}

function storePreference(scope: ActiveScope): void {
  localStorage.setItem(
    SCOPE_PREFERENCE_KEY,
    JSON.stringify({
      tenant_id: scope.tenantId,
      legal_entity_id: scope.legalEntityId,
      company_id: scope.companyId,
      operating_site_id: scope.siteId,
    })
  );
}

export interface ScopeProviderProps {
  children: React.ReactNode;
  adapter?: ScopeAdapter;
}

export const ScopeProvider: React.FC<ScopeProviderProps> = ({
  children,
  adapter = defaultScopeAdapter,
}) => {
  const { user, isAuthenticated } = useAuth();
  const [tenants, setTenants] = useState<TenantScope[]>([]);
  const [scope, setScopeState] = useState<ActiveScope | null>(null);
  const [status, setStatus] = useState<ScopeStatus>('idle');
  const [error, setError] = useState<string | null>(null);

  const clearScope = useCallback(() => {
    setScopeState(null);
    setTenants([]);
    setStatus('idle');
    setError(null);
    queryCache.clear();
    apiClient.setScopeProvider(null);
  }, []);

  const applyTrustedScope = useCallback((trustedScope: ActiveScope) => {
    queryCache.clear();
    setScopeState(trustedScope);
    setStatus('ready');
    setError(null);
    storePreference(trustedScope);
  }, []);

  useEffect(() => {
    if (!isAuthenticated || !user) {
      clearScope();
      localStorage.removeItem(SCOPE_PREFERENCE_KEY);
      return;
    }

    let cancelled = false;
    setStatus('loading');
    setError(null);
    setScopeState(null);
    queryCache.clear();

    const establish = async () => {
      try {
        const available = await adapter.fetchTenants();
        if (cancelled) return;
        setTenants(available);
        if (available.length === 0)
          throw new Error('No authorized organization scope is available.');

        const preference = readPreference();
        let result = await adapter.selectActiveScope(preference ?? { tenant_id: available[0].id });

        if (!result.valid && preference) {
          result = await adapter.selectActiveScope({ tenant_id: available[0].id });
        }
        if (!result.valid || !result.scope || !(await adapter.validateScope(result.scope))) {
          throw new Error(result.error ?? 'Backend rejected the active scope.');
        }
        if (!cancelled) applyTrustedScope(result.scope);
      } catch (caught: unknown) {
        if (!cancelled) {
          setScopeState(null);
          setStatus('unavailable');
          setError(caught instanceof Error ? caught.message : 'Organization scope is unavailable.');
        }
      }
    };

    void establish();
    return () => {
      cancelled = true;
    };
  }, [adapter, applyTrustedScope, clearScope, isAuthenticated, user]);

  useEffect(() => {
    apiClient.setScopeProvider(
      scope
        ? () => ({
            tenantId: scope.tenantId,
            legalEntityId: scope.legalEntityId ?? undefined,
            companyId: scope.companyId,
            siteId: scope.siteId,
          })
        : null
    );
    return () => apiClient.setScopeProvider(null);
  }, [scope]);

  const select = useCallback(
    async (selection: ActiveScopeSelection) => {
      setStatus('switching');
      setError(null);
      try {
        const result = await adapter.selectActiveScope(selection);
        if (!result.valid || !result.scope || !(await adapter.validateScope(result.scope))) {
          setStatus(scope ? 'ready' : 'unavailable');
          setError(result.error ?? 'Backend rejected the requested scope.');
          return;
        }
        applyTrustedScope(result.scope);
      } catch (caught: unknown) {
        setStatus(scope ? 'ready' : 'unavailable');
        setError(caught instanceof Error ? caught.message : 'Scope switch failed.');
      }
    },
    [adapter, applyTrustedScope, scope]
  );

  const setTenant = useCallback((tenantId: string) => select({ tenant_id: tenantId }), [select]);
  const setCompany = useCallback(
    (companyId: string) =>
      scope ? select({ tenant_id: scope.tenantId, company_id: companyId }) : Promise.resolve(),
    [scope, select]
  );
  const setSite = useCallback(
    (siteId: string) =>
      scope
        ? select({
            tenant_id: scope.tenantId,
            legal_entity_id: scope.legalEntityId,
            company_id: scope.companyId,
            operating_site_id: siteId,
          })
        : Promise.resolve(),
    [scope, select]
  );
  const setScope = useCallback(
    (partial: Partial<ActiveScope>) =>
      scope
        ? select({
            tenant_id: partial.tenantId ?? scope.tenantId,
            legal_entity_id: partial.legalEntityId ?? scope.legalEntityId,
            company_id: partial.companyId ?? scope.companyId,
            operating_site_id: partial.siteId ?? scope.siteId,
          })
        : Promise.resolve(),
    [scope, select]
  );

  const value = useMemo<ScopeContextValue>(
    () => ({ scope, tenants, status, error, setTenant, setCompany, setSite, setScope }),
    [scope, tenants, status, error, setTenant, setCompany, setSite, setScope]
  );

  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
};

export const useScope = (): ScopeContextValue => {
  const context = useContext(ScopeContext);
  if (!context) throw new Error('useScope must be used within ScopeProvider');
  return context;
};
