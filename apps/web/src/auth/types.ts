export type AuthenticationStrength =
  'password' | 'oidc' | 'mfa' | 'phishing_resistant' | 'break_glass' | 'unspecified';

export interface PrincipalIdentity {
  tenantId: string;
  principalId: string;
  principalType: 'user' | 'service_account' | 'system';
  authenticationStrength: AuthenticationStrength;
  scopes: Array<Record<string, string>>;
}

export interface UserProfile {
  id: string;
  email: string;
  name: string;
  tenantId: string;
  avatarUrl?: string;
  principal?: PrincipalIdentity;
}

export interface SessionInfo {
  /** Bearer credential held in memory only. */
  accessToken: string;
  expiresAt: number;
  issuedAt: number;
}

export interface AuthResponse {
  user: UserProfile;
  session: SessionInfo;
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
  refreshSession: () => Promise<void>;
}
