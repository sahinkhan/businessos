import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import { UserProfile, SessionInfo, AuthContextValue } from './types';

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const AUTH_STORAGE_KEY = 'businessos.auth.session';
const USER_STORAGE_KEY = 'businessos.auth.user';

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserProfile | null>(() => {
    try {
      const stored = localStorage.getItem(USER_STORAGE_KEY);
      return stored ? JSON.parse(stored) : null;
    } catch {
      return null;
    }
  });

  const [session, setSession] = useState<SessionInfo | null>(() => {
    try {
      const stored = localStorage.getItem(AUTH_STORAGE_KEY);
      return stored ? JSON.parse(stored) : null;
    } catch {
      return null;
    }
  });

  const [isLoading, setIsLoading] = useState<boolean>(false);

  // Default demo user for seamless Phase 4.5 baseline experience if none logged in
  useEffect(() => {
    if (!user) {
      const defaultUser: UserProfile = {
        id: 'usr_enterprise_admin',
        email: 'admin@businessos.internal',
        name: 'Enterprise Administrator',
        roles: ['admin', 'manager'],
        permissions: ['*'],
        tenantId: 'tenant_default',
      };
      const nowSec = Math.floor(Date.now() / 1000);
      const defaultSession: SessionInfo = {
        token: 'ey_demo_session_token_phase45',
        issuedAt: nowSec,
        expiresAt: nowSec + 3600 * 8, // 8 hours
      };
      setUser(defaultUser);
      setSession(defaultSession);
      try {
        localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(defaultUser));
        localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(defaultSession));
      } catch {
        // ignore
      }
    }
  }, [user]);

  const login = useCallback(async (email: string) => {
    setIsLoading(true);
    try {
      // Presentation auth boundary matching backend contract
      const nowSec = Math.floor(Date.now() / 1000);
      const newUser: UserProfile = {
        id: 'usr_' + Math.random().toString(36).substring(2, 9),
        email,
        name: email.split('@')[0],
        roles: ['user'],
        permissions: ['read', 'write'],
        tenantId: 'tenant_default',
      };
      const newSession: SessionInfo = {
        token: 'token_' + Math.random().toString(36).substring(2, 15),
        issuedAt: nowSec,
        expiresAt: nowSec + 3600 * 4,
      };

      setUser(newUser);
      setSession(newSession);
      localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(newUser));
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(newSession));
    } finally {
      setIsLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    setIsLoading(true);
    try {
      setUser(null);
      setSession(null);
      localStorage.removeItem(USER_STORAGE_KEY);
      localStorage.removeItem(AUTH_STORAGE_KEY);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const refreshToken = useCallback(async () => {
    if (session) {
      const nowSec = Math.floor(Date.now() / 1000);
      const updatedSession: SessionInfo = {
        ...session,
        expiresAt: nowSec + 3600 * 4,
      };
      setSession(updatedSession);
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(updatedSession));
    }
  }, [session]);

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
