import { apiClient } from '../api/client';
import { ApiError } from '../api/types';
import type { SessionInfo } from './types';

export interface AuthAdapter {
  getSession(): Promise<SessionInfo | null>;
  startLogin(returnTo: string): Promise<string>;
  logout(csrfToken: string): Promise<void>;
}

function parseSession(value: unknown): SessionInfo {
  if (!value || typeof value !== 'object') throw new Error('Invalid session response');
  const raw = value as Record<string, unknown>;
  const principal = raw.principal as Record<string, unknown> | undefined;
  const scope = raw.active_scope as Record<string, unknown> | undefined;
  const expiresAt = Date.parse(String(raw.expires_at)) / 1000;
  if (
    raw.status !== 'authenticated' ||
    !principal ||
    !scope ||
    typeof raw.session_id !== 'string' ||
    typeof principal.id !== 'string' ||
    typeof principal.tenant_id !== 'string' ||
    typeof scope.tenant_id !== 'string' ||
    scope.tenant_id !== principal.tenant_id ||
    typeof raw.csrf_token !== 'string' ||
    !Number.isFinite(expiresAt) ||
    expiresAt <= Date.now() / 1000
  )
    throw new Error('Invalid session response');
  const companyId = scope.company_id;
  const siteId = scope.operating_site_id;
  if (
    (companyId !== null && typeof companyId !== 'string') ||
    (siteId !== null && typeof siteId !== 'string')
  ) {
    throw new Error('Invalid session scope');
  }
  return {
    id: raw.session_id,
    user: {
      id: principal.id,
      tenantId: principal.tenant_id,
      name: typeof principal.display_name === 'string' ? principal.display_name : principal.id,
      email: typeof principal.email === 'string' ? principal.email : undefined,
    },
    tenantId: scope.tenant_id,
    companyId: companyId as string | null,
    siteId: siteId as string | null,
    csrfToken: raw.csrf_token,
    expiresAt,
  };
}

export class HttpAuthAdapter implements AuthAdapter {
  async getSession(): Promise<SessionInfo | null> {
    try {
      return parseSession(await apiClient.get('/v1/auth/session'));
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return null;
      throw error;
    }
  }
  async startLogin(returnTo: string): Promise<string> {
    const result = await apiClient.post<{ authorization_url: string }>('/v1/auth/login/start', {
      return_to: returnTo,
    });
    const url = new URL(result.authorization_url);
    if (url.protocol !== 'https:') throw new Error('Invalid authorization URL');
    return url.href;
  }
  async logout(csrfToken: string): Promise<void> {
    await apiClient.post('/v1/auth/logout', undefined, { headers: { 'X-CSRF-Token': csrfToken } });
  }
}

export const defaultAuthAdapter = new HttpAuthAdapter();
