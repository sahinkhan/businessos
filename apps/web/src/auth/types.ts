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
  status:
    | 'initializing'
    | 'authenticated'
    | 'unauthenticated'
    | 'service_unavailable'
    | 'authorization_denied';
  error: string | null;
}

export interface AuthContextValue extends AuthState {
  runSecurityTransition: SecurityTransitionRunner;
  login: (returnTo?: string) => Promise<void>;
  logout: () => Promise<void>;
  reloadSession: () => Promise<void>;
  updateSessionSecurity: (
    scope: SessionScope,
    csrfToken: string,
    expiresAt: number,
    advanceContext?: boolean
  ) => void;
}
import type { SecurityTransitionRunner } from '../api/securityTransition';
