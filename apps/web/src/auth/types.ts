export interface UserProfile {
  id: string;
  email: string;
  name: string;
  roles: string[];
  permissions: string[];
  tenantId: string;
  avatarUrl?: string;
}

export interface SessionInfo {
  token: string;
  expiresAt: number; // Unix timestamp in seconds
  issuedAt: number;
}

export interface AuthState {
  user: UserProfile | null;
  session: SessionInfo | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

export interface AuthContextValue extends AuthState {
  login: (email: string, password?: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshToken: () => Promise<void>;
}
