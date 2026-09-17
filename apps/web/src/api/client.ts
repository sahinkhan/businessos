import { ApiError, ApiErrorPayload, RequestOptions } from './types';

export type CsrfTokenProvider = () => string | null;
export type UnauthorizedHandler = () => void;

function generateCorrelationId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
  }
  return `corr_${Date.now().toString(36)}`;
}

function toErrorPayload(value: unknown, statusText: string): ApiErrorPayload {
  if (typeof value !== 'object' || value === null) {
    return { code: 'HTTP_ERROR', message: statusText || 'API request failed' };
  }
  const candidate = value as Record<string, unknown>;
  return {
    code: typeof candidate.code === 'string' ? candidate.code : 'HTTP_ERROR',
    message:
      typeof candidate.message === 'string'
        ? candidate.message
        : statusText || 'API request failed',
    details: candidate.details,
    correlationId:
      typeof candidate.correlationId === 'string' ? candidate.correlationId : undefined,
  };
}

export class ApiClient {
  private readonly baseUrl: string;
  private csrfTokenProvider: CsrfTokenProvider | null = null;
  private onUnauthorized: UnauthorizedHandler | null = null;

  constructor(baseUrl = '/api/v1') {
    this.baseUrl = baseUrl;
  }

  public setCsrfTokenProvider(provider: CsrfTokenProvider | null): void {
    this.csrfTokenProvider = provider;
  }

  public setOnUnauthorized(handler: UnauthorizedHandler | null): void {
    this.onUnauthorized = handler;
  }

  public async request<T = unknown>(endpoint: string, options: RequestOptions = {}): Promise<T> {
    const { params, body, headers: customHeaders, ...customOptions } = options;
    let url = endpoint.startsWith('http')
      ? endpoint
      : `${this.baseUrl}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;

    if (params) {
      const searchParams = new URLSearchParams();
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined) searchParams.append(key, String(value));
      }
      const query = searchParams.toString();
      if (query) url += `${url.includes('?') ? '&' : '?'}${query}`;
    }

    const headers = new Headers(customHeaders);
    headers.set('Accept', 'application/json');
    headers.set('X-Correlation-Id', generateCorrelationId());
    if (body !== undefined && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }

    const method = (customOptions.method ?? 'GET').toUpperCase();
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      const csrfToken = this.csrfTokenProvider?.();
      if (csrfToken) headers.set('X-CSRF-Token', csrfToken);
    }

    const response = await fetch(url, {
      credentials: 'same-origin',
      ...customOptions,
      headers,
      body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body),
    });

    if (response.status === 401) this.onUnauthorized?.();

    if (!response.ok) {
      let payload: unknown;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }
      throw new ApiError(response.status, toErrorPayload(payload, response.statusText));
    }

    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  public get<T = unknown>(endpoint: string, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: 'GET' });
  }

  public post<T = unknown>(endpoint: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: 'POST', body });
  }

  public put<T = unknown>(endpoint: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: 'PUT', body });
  }

  public delete<T = unknown>(endpoint: string, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: 'DELETE' });
  }
}

export const apiClient = new ApiClient();
