import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../api/client';
import { queryCache } from '../api/queryCache';
import { AuthAdapter, defaultAuthAdapter } from './authAdapter';
import { AuthContextValue, SessionInfo, UserProfile } from './types';

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export interface AuthProviderProps {
  children: React.ReactNode;
  adapter?: AuthAdapter;
  initialUser?: UserProfile | null;
  initialSession?: SessionInfo | null;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({
  children,
  adapter = defaultAuthAdapter,
  initialUser = null,
  initialSession = null,
}) => {
  const [user, setUser] = useState<UserProfile | null>(initialUser);
  const [session, setSession] = useState<SessionInfo | null>(initialSession);
  const [isLoading, setIsLoading] = useState(false);

  const invalidateSession = useCallback(() => {
    setUser(null);
    setSession(null);
    queryCache.clear();
    apiClient.setTokenProvider(null);
  }, []);

  useEffect(() => {
    apiClient.setTokenProvider(() => session?.accessToken ?? null);
    return () => apiClient.setTokenProvider(null);
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
    async (email: string, password?: string) => {
      setIsLoading(true);
      try {
        const response = await adapter.login({ email, password });
        if (response.session.expiresAt <= Math.floor(Date.now() / 1000)) {
          throw new Error('Backend returned an expired session.');
        }
        queryCache.clear();
        setUser(response.user);
        setSession(response.session);
      } finally {
        setIsLoading(false);
      }
    },
    [adapter]
  );

  const logout = useCallback(async () => {
    setIsLoading(true);
    const accessToken = session?.accessToken;
    invalidateSession();
    try {
      await adapter.logout(accessToken);
    } finally {
      setIsLoading(false);
    }
  }, [adapter, invalidateSession, session]);

  const refreshSession = useCallback(async () => {
    if (!session?.accessToken) return;
    try {
      const refreshed = await adapter.refreshSession(session.accessToken);
      setSession(refreshed);
    } catch {
      invalidateSession();
    }
  }, [adapter, invalidateSession, session]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      session,
      isAuthenticated: Boolean(
        user && session && session.expiresAt > Math.floor(Date.now() / 1000)
      ),
      isLoading,
      login,
      logout,
      refreshSession,
    }),
    [user, session, isLoading, login, logout, refreshSession]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
};
