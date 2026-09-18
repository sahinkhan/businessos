import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../api/client';
import { createSecurityTransitionCoordinator } from '../api/securityTransition';
import { queryCache } from '../api/queryCache';
import { securityContext } from '../api/securityContext';
import { ApiError } from '../api/types';
import { AuthAdapter, defaultAuthAdapter } from './authAdapter';
import { AuthContextValue, SessionInfo, SessionScope, UserProfile } from './types';

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
  const runSecurityTransition = useMemo(createSecurityTransitionCoordinator, []);
  const user = useMemo(() => (session ? userFromSession(session) : null), [session]);

  const invalidateSession = useCallback(() => {
    securityContext.advance();
    queryCache.clear();
    setSession(null);
    setIsLoading(false);
    setStatus('unauthenticated');
    setError(null);
    apiClient.setCsrfTokenProvider(null);
  }, []);

  const acceptSession = useCallback((next: SessionInfo | null) => {
    securityContext.advance();
    queryCache.clear();
    setSession(next);
    setStatus(next ? 'authenticated' : 'unauthenticated');
    setError(null);
  }, []);

  const reloadSession = useCallback(async () => {
    let attemptGeneration: number | null = null;
    setIsLoading(true);
    setStatus('initializing');
    setError(null);
    try {
      const { generation, next } = await runSecurityTransition(async () => ({
        generation: (attemptGeneration = securityContext.generation()),
        next: await adapter.getSession(),
      }));
      if (generation !== securityContext.generation()) return;
      setIsLoading(false);
      acceptSession(next);
    } catch (caught: unknown) {
      if (attemptGeneration !== null && attemptGeneration !== securityContext.generation()) return;
      securityContext.advance();
      queryCache.clear();
      setSession(null);
      setIsLoading(false);
      apiClient.setCsrfTokenProvider(null);
      setStatus(
        caught instanceof ApiError && caught.status === 403
          ? 'authorization_denied'
          : 'service_unavailable'
      );
      setError(caught instanceof Error ? caught.message : 'Session service is unavailable.');
    }
  }, [acceptSession, adapter, runSecurityTransition]);

  useEffect(() => {
    if (initialSession === null) void reloadSession();
  }, [initialSession, reloadSession]);

  useEffect(() => {
    apiClient.setCsrfTokenProvider(() => session?.csrfToken ?? null);
    return () => apiClient.setCsrfTokenProvider(null);
  }, [session]);

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
    try {
      await runSecurityTransition(() => adapter.logout());
    } finally {
      invalidateSession();
      setIsLoading(false);
    }
  }, [adapter, invalidateSession, runSecurityTransition]);

  const updateSessionSecurity = useCallback(
    (scope: SessionScope, csrfToken: string, expiresAt: number, advanceContext = true) => {
      if (advanceContext) {
        securityContext.advance();
        queryCache.clear();
      }
      setSession((current) =>
        current ? { ...current, activeScope: scope, csrfToken, expiresAt } : current
      );
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
