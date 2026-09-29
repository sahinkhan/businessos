import { securityContext } from './securityContext';
import { ApiError, RequestOptions } from './types';

/** Same-origin JSON transport. Cookies are HttpOnly; scope is server session state. */
export class ApiClient {
  constructor(private readonly baseUrl = '/api') {}

  async request<T = unknown>(endpoint: string, options: RequestOptions = {}): Promise<T> {
    if (!endpoint.startsWith('/') || endpoint.startsWith('//'))
      throw new Error('API endpoint must be same-origin');
    const { params, body, headers: suppliedHeaders, ...requestOptions } = options;
    const url = new URL(`${this.baseUrl}${endpoint}`, window.location.origin);
    if (url.origin !== window.location.origin) throw new Error('API URL must be same-origin');
    for (const [key, value] of Object.entries(params ?? {})) {
      if (value !== null && value !== undefined) url.searchParams.set(key, String(value));
    }
    const method = (requestOptions.method ?? 'GET').toUpperCase();
    const controller = new AbortController();
    const release = securityContext.track(controller);
    const suppliedSignal = requestOptions.signal;
    if (suppliedSignal?.aborted) controller.abort();
    suppliedSignal?.addEventListener('abort', () => controller.abort(), { once: true });
    const generation = securityContext.generation();
    const headers = new Headers(suppliedHeaders);
    headers.set('Accept', 'application/json');
    headers.set('X-Correlation-Id', crypto.randomUUID());
    if (body !== undefined) headers.set('Content-Type', 'application/json');
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      const csrf = securityContext.current()?.csrfToken;
      if (csrf) headers.set('X-CSRF-Token', csrf);
    }
    try {
      const response = await fetch(url, {
        ...requestOptions,
        method,
        headers,
        body:
          body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body),
        credentials: 'same-origin',
        signal: controller.signal,
      });
      if (generation !== securityContext.generation())
        throw new DOMException('Security context changed', 'AbortError');
      if (response.status === 401 && endpoint !== '/v1/auth/session') {
        window.dispatchEvent(new Event('businessos:unauthorized'));
      }
      if (!response.ok) {
        const payload = await response
          .json()
          .catch(() => ({ code: 'http_error', message: response.statusText }));
        throw new ApiError(response.status, payload);
      }
      if (response.status === 204) return undefined as T;
      return (await response.json()) as T;
    } finally {
      release();
    }
  }

  get<T = unknown>(endpoint: string, options?: RequestOptions) {
    return this.request<T>(endpoint, { ...options, method: 'GET' });
  }
  post<T = unknown>(endpoint: string, body?: unknown, options?: RequestOptions) {
    return this.request<T>(endpoint, { ...options, method: 'POST', body });
  }
  put<T = unknown>(endpoint: string, body?: unknown, options?: RequestOptions) {
    return this.request<T>(endpoint, { ...options, method: 'PUT', body });
  }
  delete<T = unknown>(endpoint: string, options?: RequestOptions) {
    return this.request<T>(endpoint, { ...options, method: 'DELETE' });
  }
}

export const apiClient = new ApiClient();
