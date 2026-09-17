import { ApiError, RequestOptions } from './types';

export type TokenProvider = () => string | null;
export type ScopeProvider = () => { tenantId?: string; companyId?: string; siteId?: string } | null;
export type UnauthorizedHandler = () => void;

function generateCorrelationId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return 'corr_' + Date.now().toString(36) + '_' + Math.random().toString(36).substring(2, 10);
}

export class ApiClient {
  private baseUrl: string;
  private tokenProvider: TokenProvider | null = null;
  private scopeProvider: ScopeProvider | null = null;
  private onUnauthorized: UnauthorizedHandler | null = null;

  constructor(baseUrl: string = '/api') {
    this.baseUrl = baseUrl;
  }

  public setTokenProvider(provider: TokenProvider | null): void {
    this.tokenProvider = provider;
  }

  public setScopeProvider(provider: ScopeProvider | null): void {
    this.scopeProvider = provider;
  }

  public setOnUnauthorized(handler: UnauthorizedHandler | null): void {
    this.onUnauthorized = handler;
  }

  private getAuthToken(): string | null {
    if (this.tokenProvider) {
      return this.tokenProvider();
    }
    try {
      const sessionStr = localStorage.getItem('businessos.auth.session');
      if (sessionStr) {
        const session = JSON.parse(sessionStr);
        return session.token || null;
      }
    } catch {
      // ignore
    }
    return null;
  }

  private getActiveScope() {
    if (this.scopeProvider) {
      return this.scopeProvider();
    }
    try {
      const scopeStr = localStorage.getItem('businessos.active_scope');
      if (scopeStr) return JSON.parse(scopeStr);
    } catch {
      // ignore
    }
    return null;
  }

  public async request<T = any>(endpoint: string, options: RequestOptions = {}): Promise<T> {
    const { params, body, headers: customHeaders, scope, ...customOptions } = options;

    let url = endpoint.startsWith('http')
      ? endpoint
      : `${this.baseUrl}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;

    if (params) {
      const searchParams = new URLSearchParams();
      Object.entries(params).forEach(([key, val]) => {
        if (val !== undefined && val !== null) {
          searchParams.append(key, String(val));
        }
      });
      const qs = searchParams.toString();
      if (qs) {
        url += (url.includes('?') ? '&' : '?') + qs;
      }
    }

    const token = this.getAuthToken();
    const activeScope = scope || this.getActiveScope();

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'X-Correlation-Id': generateCorrelationId(),
      ...(customHeaders as Record<string, string>),
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    if (activeScope?.tenantId) {
      headers['X-Tenant-Id'] = activeScope.tenantId;
    }
    if (activeScope?.companyId) {
      headers['X-Company-Id'] = activeScope.companyId;
    }
    if (activeScope?.siteId) {
      headers['X-Operating-Site-Id'] = activeScope.siteId;
    }

    const config: RequestInit = {
      ...customOptions,
      headers,
    };

    if (body !== undefined) {
      config.body = typeof body === 'string' ? body : JSON.stringify(body);
    }

    const response = await fetch(url, config);

    if (response.status === 401) {
      this.onUnauthorized?.();
    }

    if (!response.ok) {
      let errorPayload = { code: 'HTTP_ERROR', message: response.statusText };
      try {
        errorPayload = await response.json();
      } catch {
        // ignore
      }
      throw new ApiError(response.status, errorPayload);
    }

    if (response.status === 204) {
      return {} as T;
    }

    return (await response.json()) as T;
  }

  public get<T = any>(endpoint: string, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: 'GET' });
  }

  public post<T = any>(endpoint: string, body?: any, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: 'POST', body });
  }

  public put<T = any>(endpoint: string, body?: any, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: 'PUT', body });
  }

  public delete<T = any>(endpoint: string, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: 'DELETE' });
  }
}

export const apiClient = new ApiClient();
