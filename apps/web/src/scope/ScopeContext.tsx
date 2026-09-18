import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { queryCache } from '../api/queryCache';
import { securityContext } from '../api/securityContext';
import { ApiError } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { SessionScope } from '../auth/types';
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

function projectSessionScope(active: SessionScope, tenants: TenantScope[]): ActiveScope {
  const tenant = tenants.find((item) => item.id === active.tenantId);
  const group = tenant?.groups.find((item) => item.id === active.enterpriseGroupId);
  const companies = tenant?.groups.flatMap((item) => item.companies) ?? [];
  const company = companies.find((item) => item.id === (active.companyId ?? active.legalEntityId));
  const site = companies
    .flatMap((item) => item.sites)
    .find((item) => item.id === active.operatingSiteId);
  return {
    tenantId: active.tenantId,
    tenantName: tenant?.name ?? active.tenantId,
    groupId: active.enterpriseGroupId,
    groupName: group?.name ?? null,
    legalEntityId: active.legalEntityId,
    companyId: active.companyId,
    companyName: company?.name ?? null,
    siteId: active.operatingSiteId,
    siteName: site?.name ?? null,
  };
}

export interface ScopeProviderProps {
  children: React.ReactNode;
  adapter?: ScopeAdapter;
}

export const ScopeProvider: React.FC<ScopeProviderProps> = ({
  children,
  adapter = defaultScopeAdapter,
}) => {
  const {
    user,
    session,
    isAuthenticated,
    status: authStatus,
    reconcileAuthoritativeSession,
    rejectAuthoritativeSession,
    updateSessionSecurity,
    runSecurityTransition,
  } = useAuth();
  const principalKey = isAuthenticated && user ? `${user.tenantId}:${user.id}` : null;
  const emptyScopeStatus: ScopeStatus =
    !principalKey && (authStatus === 'service_unavailable' || authStatus === 'authorization_denied')
      ? 'unavailable'
      : 'idle';
  const [tenants, setTenants] = useState<TenantScope[]>([]);
  const [scope, setScopeState] = useState<ActiveScope | null>(null);
  const [status, setStatus] = useState<ScopeStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const tenantsRef = useRef<TenantScope[]>([]);
  const scopeRef = useRef<ActiveScope | null>(null);
  const desiredTransitionRef = useRef<{
    id: number;
    selection: ActiveScopeSelection;
  } | null>(null);
  const transitionWorkerRef = useRef<Promise<void> | null>(null);
  const transitionIdRef = useRef(0);
  const sessionSecurityRef = useRef({
    csrfToken: session?.csrfToken,
    expiresAt: session?.expiresAt,
  });
  sessionSecurityRef.current = {
    csrfToken: session?.csrfToken,
    expiresAt: session?.expiresAt,
  };
  tenantsRef.current = tenants;

  const sessionProjection = useMemo(
    () => (session ? projectSessionScope(session.activeScope, tenants) : null),
    [session, tenants]
  );
  const sessionHasDetailedScope = Boolean(
    session?.activeScope.enterpriseGroupId ||
    session?.activeScope.legalEntityId ||
    session?.activeScope.companyId ||
    session?.activeScope.operatingSiteId
  );
  const activeScope =
    session && status !== 'unavailable'
      ? sessionHasDetailedScope
        ? sessionProjection
        : (scope ?? sessionProjection)
      : null;

  const clearScope = useCallback(() => {
    securityContext.advance();
    scopeRef.current = null;
    setScopeState(null);
    setTenants([]);
    setStatus('idle');
    setError(null);
    queryCache.clear();
  }, []);

  const applyTrustedScope = useCallback((trustedScope: ActiveScope) => {
    securityContext.advance();
    queryCache.clear();
    scopeRef.current = trustedScope;
    setScopeState(trustedScope);
    setStatus('ready');
    setError(null);
    storePreference(trustedScope);
  }, []);

  const commitTrustedTransition = useCallback(
    (result: { scope: ActiveScope; csrfToken: string; expiresAt: number }) => {
      securityContext.advance();
      queryCache.clear();
      scopeRef.current = result.scope;
      setScopeState(result.scope);
      setStatus('ready');
      storePreference(result.scope);
      updateSessionSecurity(
        {
          tenantId: result.scope.tenantId,
          enterpriseGroupId: result.scope.groupId,
          legalEntityId: result.scope.legalEntityId,
          companyId: result.scope.companyId,
          operatingSiteId: result.scope.siteId,
        },
        result.csrfToken,
        result.expiresAt,
        false
      );
    },
    [updateSessionSecurity]
  );

  useEffect(() => {
    if (!principalKey) {
      clearScope();
      setStatus(emptyScopeStatus);
      localStorage.removeItem(SCOPE_PREFERENCE_KEY);
      return;
    }

    let cancelled = false;
    securityContext.advance();
    setStatus('loading');
    setError(null);
    setScopeState(null);
    queryCache.clear();

    const establish = async () => {
      try {
        const available = await adapter.fetchTenants();
        if (cancelled) return;
        tenantsRef.current = available;
        setTenants(available);
        if (available.length === 0)
          throw new Error('No authorized organization scope is available.');

        const preference = readPreference();
        const result = await runSecurityTransition(async () => {
          let selected = await adapter.selectActiveScope(
            preference ?? { tenant_id: available[0].id }
          );
          if (!selected.valid && preference) {
            selected = await adapter.selectActiveScope({ tenant_id: available[0].id });
          }
          return selected;
        });
        if (!result.valid || !result.scope) {
          throw new Error(result.error ?? 'Backend rejected the active scope.');
        }
        if (!cancelled) {
          if (result.csrfToken && result.expiresAt) {
            commitTrustedTransition({
              scope: result.scope,
              csrfToken: result.csrfToken,
              expiresAt: result.expiresAt,
            });
          } else {
            applyTrustedScope(result.scope);
          }
        }
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
  }, [
    adapter,
    applyTrustedScope,
    clearScope,
    commitTrustedTransition,
    emptyScopeStatus,
    principalKey,
    runSecurityTransition,
  ]);

  const select = useCallback(
    (selection: ActiveScopeSelection) => {
      const id = ++transitionIdRef.current;
      desiredTransitionRef.current = { id, selection };
      securityContext.advance();
      queryCache.clear();
      setStatus('switching');
      setError(null);
      if (!transitionWorkerRef.current) {
        transitionWorkerRef.current = runSecurityTransition(async () => {
          let processedId = 0;
          let nextCsrfToken: string | undefined;
          let lastAccepted:
            { scope: ActiveScope; csrfToken: string; expiresAt: number } | undefined;
          while (desiredTransitionRef.current?.id !== processedId) {
            const target = desiredTransitionRef.current;
            if (!target) break;
            processedId = target.id;
            let result;
            try {
              result = await adapter.selectActiveScope(target.selection, nextCsrfToken);
            } catch (caught: unknown) {
              const message = caught instanceof Error ? caught.message : 'Scope switch failed.';

              // These codes are raised before the Organization mutation handler runs. Other 403
              // and conflict responses remain ambiguous and require a current-session read.
              if (
                caught instanceof ApiError &&
                caught.status === 403 &&
                ['forbidden', 'invalid_csrf'].includes(caught.code) &&
                lastAccepted
              ) {
                nextCsrfToken = lastAccepted.csrfToken;
                if (desiredTransitionRef.current?.id !== processedId) continue;
                commitTrustedTransition(lastAccepted);
                setError(message);
                break;
              }

              try {
                let reconciled = await reconcileAuthoritativeSession();
                while (
                  reconciled.status === 'stale' &&
                  desiredTransitionRef.current?.id !== processedId
                ) {
                  reconciled = await reconcileAuthoritativeSession();
                }
                if (reconciled.status === 'stale') break;
                if (reconciled.session === null) {
                  scopeRef.current = null;
                  setScopeState(null);
                  setStatus('idle');
                  setError(message);
                  break;
                }
                const authoritative = projectSessionScope(
                  reconciled.session.activeScope,
                  tenantsRef.current
                );
                nextCsrfToken = reconciled.session.csrfToken;
                lastAccepted = {
                  scope: authoritative,
                  csrfToken: reconciled.session.csrfToken,
                  expiresAt: reconciled.session.expiresAt,
                };
                scopeRef.current = authoritative;
                setScopeState(authoritative);
                storePreference(authoritative);
                if (desiredTransitionRef.current?.id !== processedId) continue;
                setStatus('ready');
                setError(message);
              } catch (reconciliationFailure: unknown) {
                rejectAuthoritativeSession(reconciliationFailure);
                scopeRef.current = null;
                setScopeState(null);
                setStatus('unavailable');
                setError(
                  reconciliationFailure instanceof Error
                    ? reconciliationFailure.message
                    : 'Authoritative session reconciliation failed.'
                );
              }
              break;
            }
            const acceptedCsrf =
              result.csrfToken ?? nextCsrfToken ?? sessionSecurityRef.current.csrfToken;
            const acceptedExpiry = result.expiresAt ?? sessionSecurityRef.current.expiresAt;
            if (result.valid && result.scope && acceptedCsrf && acceptedExpiry) {
              nextCsrfToken = acceptedCsrf;
              lastAccepted = {
                scope: result.scope,
                csrfToken: acceptedCsrf,
                expiresAt: acceptedExpiry,
              };
              sessionSecurityRef.current = {
                csrfToken: acceptedCsrf,
                expiresAt: acceptedExpiry,
              };
              if (desiredTransitionRef.current?.id === processedId) {
                commitTrustedTransition(lastAccepted);
                setError(null);
              }
              continue;
            }
            if (desiredTransitionRef.current?.id !== processedId) continue;
            if (lastAccepted) commitTrustedTransition(lastAccepted);
            setError(result.error ?? 'Backend rejected the requested scope.');
            break;
          }
        })
          .catch((caught: unknown) => {
            setError(caught instanceof Error ? caught.message : 'Scope switch failed.');
          })
          .finally(() => {
            transitionWorkerRef.current = null;
            desiredTransitionRef.current = null;
            setStatus((current) =>
              current === 'idle' || current === 'unavailable'
                ? current
                : scopeRef.current
                  ? 'ready'
                  : 'unavailable'
            );
          });
      }
      return transitionWorkerRef.current;
    },
    [
      adapter,
      commitTrustedTransition,
      reconcileAuthoritativeSession,
      rejectAuthoritativeSession,
      runSecurityTransition,
    ]
  );

  const retainCurrentScope = useCallback(() => {
    if (!activeScope || status !== 'switching') return Promise.resolve();
    return select({
      tenant_id: activeScope.tenantId,
      legal_entity_id: activeScope.legalEntityId,
      company_id: activeScope.companyId,
      operating_site_id: activeScope.siteId,
    });
  }, [activeScope, select, status]);

  const setTenant = useCallback(
    (tenantId: string) =>
      activeScope?.tenantId === tenantId ? retainCurrentScope() : select({ tenant_id: tenantId }),
    [activeScope?.tenantId, retainCurrentScope, select]
  );
  const setCompany = useCallback(
    (companyId: string) =>
      activeScope && activeScope.companyId !== companyId
        ? select({ tenant_id: activeScope.tenantId, company_id: companyId })
        : retainCurrentScope(),
    [activeScope, retainCurrentScope, select]
  );
  const setSite = useCallback(
    (siteId: string) =>
      activeScope && activeScope.siteId !== siteId
        ? select({
            tenant_id: activeScope.tenantId,
            legal_entity_id: activeScope.legalEntityId,
            company_id: activeScope.companyId ?? undefined,
            operating_site_id: siteId,
          })
        : retainCurrentScope(),
    [activeScope, retainCurrentScope, select]
  );
  const setScope = useCallback(
    (partial: Partial<ActiveScope>) => {
      if (!activeScope) return Promise.resolve();
      const selection = {
        tenant_id: partial.tenantId ?? activeScope.tenantId,
        legal_entity_id: partial.legalEntityId ?? activeScope.legalEntityId,
        company_id: partial.companyId ?? activeScope.companyId ?? undefined,
        operating_site_id: partial.siteId ?? activeScope.siteId,
      };
      if (
        selection.tenant_id === activeScope.tenantId &&
        selection.legal_entity_id === activeScope.legalEntityId &&
        selection.company_id === activeScope.companyId &&
        selection.operating_site_id === activeScope.siteId
      ) {
        return retainCurrentScope();
      }
      return select(selection);
    },
    [activeScope, retainCurrentScope, select]
  );

  const value = useMemo<ScopeContextValue>(
    () => ({
      scope: activeScope,
      tenants,
      status,
      error,
      setTenant,
      setCompany,
      setSite,
      setScope,
    }),
    [activeScope, tenants, status, error, setTenant, setCompany, setSite, setScope]
  );

  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
};

export const useScope = (): ScopeContextValue => {
  const context = useContext(ScopeContext);
  if (!context) throw new Error('useScope must be used within ScopeProvider');
  return context;
};
