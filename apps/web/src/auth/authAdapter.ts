import { apiClient } from '../api/client';
import { ApiError } from '../api/types';
import { SessionInfo } from './types';

export interface LoginStart {
  authorizationUrl: string;
  expiresAt: number;
}

export interface AuthAdapter {
  getSession(): Promise<SessionInfo | null>;
  startLogin(returnTo?: string): Promise<LoginStart>;
  logout(): Promise<void>;
}

const optionalString = (value: unknown): string | undefined =>
  typeof value === 'string' ? value : undefined;

const nullableString = (value: unknown): string | null | undefined =>
  value === null ? null : optionalString(value);

function parseSession(value: unknown): SessionInfo | null {
  if (typeof value !== 'object' || value === null) {
    throw new Error('Malformed current-session response');
  }
  const response = value as Record<string, unknown>;
  const principal = response.principal;
  const scope = response.active_scope;
  if (
    response.status !== 'authenticated' ||
    typeof principal !== 'object' ||
    principal === null ||
    typeof scope !== 'object' ||
    scope === null ||
    typeof response.expires_at !== 'string' ||
    typeof response.csrf_token !== 'string'
  ) {
    throw new Error('Malformed current-session response');
  }
  const p = principal as Record<string, unknown>;
  const s = scope as Record<string, unknown>;
  const expiresAt = Date.parse(response.expires_at) / 1000;
  if (
    typeof p.id !== 'string' ||
    typeof p.tenant_id !== 'string' ||
    !['user', 'service_account', 'device'].includes(String(p.type)) ||
    typeof p.authentication_strength !== 'string' ||
    typeof s.tenant_id !== 'string' ||
    !Number.isFinite(expiresAt)
  ) {
    throw new Error('Malformed current-session response');
  }
  return {
    principal: {
      id: p.id,
      tenantId: p.tenant_id,
      type: p.type as 'user' | 'service_account' | 'device',
      displayName: optionalString(p.display_name),
      email: optionalString(p.email),
      authenticationStrength: p.authentication_strength,
    },
    activeScope: {
      tenantId: s.tenant_id,
      enterpriseGroupId: nullableString(s.enterprise_group_id),
      legalEntityId: nullableString(s.legal_entity_id),
      companyId: nullableString(s.company_id),
      operatingSiteId: nullableString(s.operating_site_id),
    },
    expiresAt,
    csrfToken: response.csrf_token,
  };
}

export class HttpAuthAdapter implements AuthAdapter {
  constructor(private readonly baseUrl = '/auth') {}

  public async getSession(): Promise<SessionInfo | null> {
    try {
      return parseSession(await apiClient.get<unknown>(`${this.baseUrl}/session`));
    } catch (caught: unknown) {
      if (caught instanceof ApiError && caught.status === 401) return null;
      throw caught;
    }
  }

  public async startLogin(returnTo?: string): Promise<LoginStart> {
    const response = await apiClient.post<unknown>(`${this.baseUrl}/login/start`, {
      return_to: returnTo,
    });
    if (typeof response !== 'object' || response === null) {
      throw new Error('Malformed login-start response');
    }
    const value = response as Record<string, unknown>;
    const expiresAt =
      typeof value.expires_at === 'string' ? Date.parse(value.expires_at) / 1000 : Number.NaN;
    if (typeof value.authorization_url !== 'string' || !Number.isFinite(expiresAt)) {
      throw new Error('Malformed login-start response');
    }
    return { authorizationUrl: value.authorization_url, expiresAt };
  }

  public async logout(): Promise<void> {
    await apiClient.post(`${this.baseUrl}/logout`);
  }
}

export class MockAuthAdapter implements AuthAdapter {
  constructor(private session: SessionInfo | null) {}

  public async getSession(): Promise<SessionInfo | null> {
    return this.session;
  }

  public async startLogin(): Promise<LoginStart> {
    return { authorizationUrl: '/test-identity-provider', expiresAt: Date.now() / 1000 + 300 };
  }

  public async logout(): Promise<void> {
    this.session = null;
  }
}

export const defaultAuthAdapter = new HttpAuthAdapter();
