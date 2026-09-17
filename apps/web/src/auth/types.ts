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
  roles: string[];
  permissions?: string[];
  tenantId: string;
  avatarUrl?: string;
  principal?: PrincipalIdentity;
}

export interface SessionInfo {
  token: string;
  expiresAt: number; // Unix timestamp in seconds
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
  refreshToken: () => Promise<void>;
}
