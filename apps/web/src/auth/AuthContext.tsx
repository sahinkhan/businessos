import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
} from 'react';
import { securityContext } from '../api/securityContext';
import { AuthAdapter, defaultAuthAdapter } from './authAdapter';
import { AuthContextValue, AuthStatus, SessionInfo } from './types';

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode; adapter?: AuthAdapter }> = ({
  children,
  adapter = defaultAuthAdapter,
}) => {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [status, setStatus] = useState<AuthStatus>('initializing');
  const requestVersion = useRef(0);

  const install = useCallback((next: SessionInfo | null) => {
    securityContext.transition(
      next && {
        sessionId: next.id,
        userId: next.user.id,
        tenantId: next.tenantId,
        companyId: next.companyId,
        siteId: next.siteId,
        csrfToken: next.csrfToken,
      }
    );
    setSession(next);
    setStatus(next ? 'authenticated' : 'unauthenticated');
  }, []);

  const refreshToken = useCallback(async () => {
    const version = ++requestVersion.current;
    try {
      const next = await adapter.getSession();
      if (version === requestVersion.current) install(next);
    } catch {
      if (version === requestVersion.current) {
        install(null);
        setStatus('service_unavailable');
      }
    }
  }, [adapter, install]);

  useEffect(() => {
    void refreshToken();
    return () => {
      requestVersion.current += 1;
      securityContext.transition(null);
    };
  }, [refreshToken]);

  useEffect(() => {
    const onUnauthorized = () => {
      requestVersion.current += 1;
      install(null);
    };
    window.addEventListener('businessos:unauthorized', onUnauthorized);
    return () => window.removeEventListener('businessos:unauthorized', onUnauthorized);
  }, [install]);

  useEffect(() => {
    if (!session) return;
    const delay = Math.max(0, session.expiresAt * 1000 - Date.now());
    const timer = window.setTimeout(() => {
      requestVersion.current += 1;
      install(null);
      setStatus('initializing');
      void refreshToken();
    }, delay);
    return () => window.clearTimeout(timer);
  }, [session, install, refreshToken]);

  const login = useCallback(
    async (returnTo = '/') => {
      const url = await adapter.startLogin(returnTo);
      window.location.assign(url);
    },
    [adapter]
  );

  const logout = useCallback(async () => {
    requestVersion.current += 1;
    const csrf = session?.csrfToken;
    install(null);
    if (csrf) await adapter.logout(csrf);
  }, [adapter, install, session]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user: session?.user ?? null,
      session,
      status,
      isAuthenticated: status === 'authenticated' && Boolean(session),
      isLoading: status === 'initializing',
      login,
      logout,
      refreshToken,
    }),
    [session, status, login, logout, refreshToken]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
};
