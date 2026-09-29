export interface UserProfile {
  id: string;
  email?: string;
  name: string;
  tenantId: string;
  avatarUrl?: string;
}

export interface SessionInfo {
  id: string;
  user: UserProfile;
  tenantId: string;
  companyId: string | null;
  siteId: string | null;
  csrfToken: string;
  expiresAt: number;
}

export type AuthStatus =
  'initializing' | 'authenticated' | 'unauthenticated' | 'service_unavailable';

export interface AuthContextValue {
  user: UserProfile | null;
  session: SessionInfo | null;
  status: AuthStatus;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (returnTo?: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshToken: () => Promise<void>;
}
