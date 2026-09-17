import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import { UserProfile, SessionInfo, AuthContextValue } from './types';
import { AuthAdapter, defaultAuthAdapter } from './authAdapter';
import { apiClient } from '../api/client';

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const AUTH_STORAGE_KEY = 'businessos.auth.session';
const USER_STORAGE_KEY = 'businessos.auth.user';

export interface AuthProviderProps {
  children: React.ReactNode;
  adapter?: AuthAdapter;
  initialUser?: UserProfile | null;
  initialSession?: SessionInfo | null;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({
  children,
  adapter = defaultAuthAdapter,
  initialUser,
  initialSession,
}) => {
  const [user, setUser] = useState<UserProfile | null>(() => {
    if (initialUser !== undefined) return initialUser;
    try {
      const stored = localStorage.getItem(USER_STORAGE_KEY);
      return stored ? JSON.parse(stored) : null;
    } catch {
      return null;
    }
  });

  const [session, setSession] = useState<SessionInfo | null>(() => {
    if (initialSession !== undefined) return initialSession;
    try {
      const stored = localStorage.getItem(AUTH_STORAGE_KEY);
      return stored ? JSON.parse(stored) : null;
    } catch {
      return null;
    }
  });

  const [isLoading, setIsLoading] = useState<boolean>(false);

  // Wire ApiClient token provider and 401 unauthorized handler
  useEffect(() => {
    apiClient.setTokenProvider(() => session?.token || null);
  }, [session]);

  const logout = useCallback(async () => {
    setIsLoading(true);
    try {
      if (session?.token) {
        await adapter.logout(session.token);
      }
    } finally {
      setUser(null);
      setSession(null);
      try {
        localStorage.removeItem(USER_STORAGE_KEY);
        localStorage.removeItem(AUTH_STORAGE_KEY);
      } catch {
        // ignore
      }
      setIsLoading(false);
    }
  }, [session, adapter]);

  useEffect(() => {
    apiClient.setOnUnauthorized(() => {
      logout();
    });
    return () => {
      apiClient.setOnUnauthorized(null);
    };
  }, [logout]);

  const sessionToken = session?.token;
  const sessionExpiresAt = session?.expiresAt;

  // On mount: validate existing session against trusted backend
  useEffect(() => {
    if (initialUser !== undefined || initialSession !== undefined) {
      return;
    }

    const validateExistingSession = async () => {
      if (!sessionToken || sessionExpiresAt === undefined) {
        return;
      }

      // Check client-side expiry first
      const nowSec = Math.floor(Date.now() / 1000);
      if (sessionExpiresAt <= nowSec) {
        await logout();
        return;
      }

      // Validate with authoritative backend
      try {
        const result = await adapter.validateSession(sessionToken);
        if (result && result.user && result.session) {
          setUser(result.user);
          setSession(result.session);
          localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(result.user));
          localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(result.session));
        } else {
          await logout();
        }
      } catch {
        // If validation fails, safely enforce unauthenticated state
        await logout();
      }
    };

    validateExistingSession();
  }, [adapter, logout, initialUser, initialSession, sessionToken, sessionExpiresAt]);

  const login = useCallback(
    async (email: string, password?: string) => {
      setIsLoading(true);
      try {
        const response = await adapter.login({ email, password });
        setUser(response.user);
        setSession(response.session);
        try {
          localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(response.user));
          localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(response.session));
        } catch {
          // ignore
        }
      } finally {
        setIsLoading(false);
      }
    },
    [adapter]
  );

  const refreshToken = useCallback(async () => {
    if (!session?.token) return;
    try {
      const refreshed = await adapter.refreshToken(session.token);
      setSession(refreshed);
      try {
        localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(refreshed));
      } catch {
        // ignore
      }
    } catch {
      await logout();
    }
  }, [session, adapter, logout]);

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
      refreshToken,
    }),
    [user, session, isLoading, login, logout, refreshToken]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
