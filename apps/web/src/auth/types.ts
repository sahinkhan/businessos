export type AuthenticationStrength =
  'oidc' | 'mfa' | 'phishing_resistant' | 'break_glass' | 'unspecified';

export interface PrincipalIdentity {
  id: string;
  tenantId: string;
  type: 'user' | 'service_account' | 'device';
  displayName?: string;
  email?: string;
  authenticationStrength: AuthenticationStrength | string;
}

export interface SessionScope {
  tenantId: string;
  enterpriseGroupId?: string | null;
  legalEntityId?: string | null;
  companyId?: string | null;
  operatingSiteId?: string | null;
}

export interface SessionInfo {
  principal: PrincipalIdentity;
  activeScope: SessionScope;
  expiresAt: number;
  csrfToken: string;
}

export interface UserProfile {
  id: string;
  email?: string;
  name: string;
  tenantId: string;
  avatarUrl?: string;
  principal: PrincipalIdentity;
}

export interface AuthState {
  user: UserProfile | null;
  session: SessionInfo | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

export interface AuthContextValue extends AuthState {
  login: (returnTo?: string) => Promise<void>;
  logout: () => Promise<void>;
  reloadSession: () => Promise<void>;
  updateSessionSecurity: (scope: SessionScope, csrfToken: string, expiresAt: number) => void;
}
