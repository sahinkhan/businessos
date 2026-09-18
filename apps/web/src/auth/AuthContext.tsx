import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { apiClient } from '../api/client';
import { createSecurityTransitionCoordinator } from '../api/securityTransition';
import { queryCache } from '../api/queryCache';
import { securityContext } from '../api/securityContext';
import { ApiError } from '../api/types';
import { AuthAdapter, defaultAuthAdapter } from './authAdapter';
import {
  AuthContextValue,
  SessionInfo,
  SessionReconciliation,
  SessionScope,
  UserProfile,
} from './types';

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export interface AuthProviderProps {
  children: React.ReactNode;
  adapter?: AuthAdapter;
  initialSession?: SessionInfo | null;
  initialUser?: UserProfile | null;
}

function userFromSession(session: SessionInfo): UserProfile {
  const principal = session.principal;
  return {
    id: principal.id,
    email: principal.email,
    name: principal.displayName ?? principal.email ?? principal.id,
    tenantId: principal.tenantId,
    principal,
  };
}

export const AuthProvider: React.FC<AuthProviderProps> = ({
  children,
  adapter = defaultAuthAdapter,
  initialSession = null,
}) => {
  const [session, setSession] = useState<SessionInfo | null>(initialSession);
  const [isLoading, setIsLoading] = useState(initialSession === null);
  const [status, setStatus] = useState<AuthContextValue['status']>(
    initialSession ? 'authenticated' : 'initializing'
  );
  const [error, setError] = useState<string | null>(null);
  const sessionRef = useRef<SessionInfo | null>(initialSession);
  const runSecurityTransition = useMemo(createSecurityTransitionCoordinator, []);
  const user = useMemo(() => (session ? userFromSession(session) : null), [session]);

  const invalidateSession = useCallback(() => {
    securityContext.advance();
    queryCache.clear();
    sessionRef.current = null;
    setSession(null);
    setIsLoading(false);
    setStatus('unauthenticated');
    setError(null);
  }, []);

  const acceptSession = useCallback((next: SessionInfo | null) => {
    securityContext.advance();
    queryCache.clear();
    sessionRef.current = next;
    setSession(next);
    setStatus(next ? 'authenticated' : 'unauthenticated');
    setError(null);
  }, []);

  const rejectAuthoritativeSession = useCallback((caught: unknown) => {
    securityContext.advance();
    queryCache.clear();
    sessionRef.current = null;
    setSession(null);
    setIsLoading(false);
    setStatus(
      caught instanceof ApiError && caught.status === 403
        ? 'authorization_denied'
        : 'service_unavailable'
    );
    setError(caught instanceof Error ? caught.message : 'Session service is unavailable.');
  }, []);

  const reconcileAuthoritativeSession = useCallback(async (): Promise<SessionReconciliation> => {
    const generation = securityContext.generation();
    const next = await adapter.getSession();
    if (generation !== securityContext.generation()) {
      // A 401 invokes the global unauthorized handler before getSession resolves null.
      if (next === null && sessionRef.current === null) {
        return { status: 'accepted', session: null };
      }
      return { status: 'stale', session: null };
    }
    acceptSession(next);
    return { status: 'accepted', session: next };
  }, [acceptSession, adapter]);

  const reloadSession = useCallback(async () => {
    let attemptGeneration: number | null = null;
    setIsLoading(true);
    setStatus('initializing');
    setError(null);
    try {
      const result = await runSecurityTransition(async () => {
        attemptGeneration = securityContext.generation();
        return reconcileAuthoritativeSession();
      });
      if (result.status === 'stale') return;
      setIsLoading(false);
    } catch (caught: unknown) {
      if (attemptGeneration !== null && attemptGeneration !== securityContext.generation()) return;
      rejectAuthoritativeSession(caught);
    }
  }, [reconcileAuthoritativeSession, rejectAuthoritativeSession, runSecurityTransition]);

  useEffect(() => {
    if (initialSession === null) void reloadSession();
  }, [initialSession, reloadSession]);

  useEffect(() => {
    apiClient.setCsrfTokenProvider(() => sessionRef.current?.csrfToken ?? null);
    return () => apiClient.setCsrfTokenProvider(null);
  }, []);

  useEffect(() => {
    apiClient.setOnUnauthorized(invalidateSession);
    return () => apiClient.setOnUnauthorized(null);
  }, [invalidateSession]);

  useEffect(() => {
    if (!session) return;
    const remainingMs = session.expiresAt * 1000 - Date.now();
    if (remainingMs <= 0) {
      invalidateSession();
      return;
    }
    const timeout = window.setTimeout(invalidateSession, remainingMs);
    return () => window.clearTimeout(timeout);
  }, [session, invalidateSession]);

  const login = useCallback(
    async (returnTo?: string) => {
      setIsLoading(true);
      try {
        const started = await adapter.startLogin(returnTo);
        window.location.assign(started.authorizationUrl);
      } finally {
        setIsLoading(false);
      }
    },
    [adapter]
  );

  const logout = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    const outcome = await runSecurityTransition(async (): Promise<unknown | null> => {
      try {
        await adapter.logout(sessionRef.current?.csrfToken);
        return null;
      } catch (caught: unknown) {
        if (caught instanceof ApiError && caught.status === 401) return null;
        if (!(
          caught instanceof ApiError &&
          caught.status === 403 &&
          caught.code === 'invalid_csrf'
        )) {
          return caught;
        }

        let reconciled: SessionReconciliation;
        try {
          reconciled = await reconcileAuthoritativeSession();
        } catch (reconciliationFailure: unknown) {
          return reconciliationFailure;
        }
        if (reconciled.status === 'stale') {
          return sessionRef.current === null
            ? null
            : new Error('Session changed while logout was being reconciled.');
        }
        if (reconciled.session === null) return null;

        try {
          await adapter.logout(reconciled.session.csrfToken);
          return null;
        } catch (retryFailure: unknown) {
          if (retryFailure instanceof ApiError && retryFailure.status === 401) return null;
          return retryFailure;
        }
      }
    });

    if (outcome === null) {
      invalidateSession();
      return;
    }

    setIsLoading(false);
    setStatus(
      outcome instanceof ApiError && outcome.status === 403
        ? 'authorization_denied'
        : 'service_unavailable'
    );
    setError(outcome instanceof Error ? outcome.message : 'Logout could not be confirmed.');
  }, [adapter, invalidateSession, reconcileAuthoritativeSession, runSecurityTransition]);

  const updateSessionSecurity = useCallback(
    (scope: SessionScope, csrfToken: string, expiresAt: number, advanceContext = true) => {
      if (advanceContext) {
        securityContext.advance();
        queryCache.clear();
      }
      const current = sessionRef.current;
      if (!current) return;
      const next = { ...current, activeScope: scope, csrfToken, expiresAt };
      sessionRef.current = next;
      setSession(next);
      setStatus('authenticated');
      setError(null);
    },
    []
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      session,
      isAuthenticated: Boolean(session && session.expiresAt > Date.now() / 1000),
      isLoading,
      status,
      error,
      login,
      logout,
      reloadSession,
      reconcileAuthoritativeSession,
      rejectAuthoritativeSession,
      updateSessionSecurity,
      runSecurityTransition,
    }),
    [
      user,
      session,
      isLoading,
      status,
      error,
      login,
      logout,
      reloadSession,
      reconcileAuthoritativeSession,
      rejectAuthoritativeSession,
      updateSessionSecurity,
      runSecurityTransition,
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
};
