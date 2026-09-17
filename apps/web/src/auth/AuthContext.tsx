import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../api/client';
import { queryCache } from '../api/queryCache';
import { securityContext } from '../api/securityContext';
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
  const user = session ? userFromSession(session) : null;

  const invalidateSession = useCallback(() => {
    securityContext.advance();
    queryCache.clear();
    setSession(null);
    apiClient.setCsrfTokenProvider(null);
  }, []);

  const acceptSession = useCallback((next: SessionInfo | null) => {
    securityContext.advance();
    queryCache.clear();
    setSession(next);
  }, []);

  const reloadSession = useCallback(async () => {
    const generation = securityContext.generation();
    setIsLoading(true);
    try {
      const next = await adapter.getSession();
      if (generation !== securityContext.generation()) return;
      setIsLoading(false);
      acceptSession(next);
    } catch {
      if (generation !== securityContext.generation()) return;
      setIsLoading(false);
      invalidateSession();
    }
  }, [acceptSession, adapter, invalidateSession]);

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
      await adapter.logout();
    } finally {
      invalidateSession();
      setIsLoading(false);
    }
  }, [adapter, invalidateSession]);

  const updateSessionSecurity = useCallback(
    (scope: SessionScope, csrfToken: string, expiresAt: number) => {
      securityContext.advance();
      queryCache.clear();
      setSession((current) =>
        current ? { ...current, activeScope: scope, csrfToken, expiresAt } : current
      );
    },
    []
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      session,
      isAuthenticated: Boolean(session && session.expiresAt > Date.now() / 1000),
      isLoading,
      login,
      logout,
      reloadSession,
      updateSessionSecurity,
    }),
    [user, session, isLoading, login, logout, reloadSession, updateSessionSecurity]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
};
