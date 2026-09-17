import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../../src/api/client';
import { ApiError } from '../../src/api/types';

describe('ApiClient hardening', () => {
  let client: ApiClient;

  beforeEach(() => {
    client = new ApiClient('/api');
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('uses only registered in-memory credential and trusted scope providers', async () => {
    localStorage.setItem('businessos.auth.session', JSON.stringify({ token: 'persisted' }));
    client.setTokenProvider(() => 'memory_credential');
    client.setScopeProvider(() => ({
      tenantId: 'tenant_123',
      legalEntityId: 'legal_234',
      companyId: 'company_456',
      siteId: 'site_789',
    }));

    let capturedHeaders = new Headers();
    global.fetch = vi.fn().mockImplementation((_url, init: RequestInit) => {
      capturedHeaders = new Headers(init.headers);
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ success: true }),
      });
    });

    await expect(client.get('/test-endpoint')).resolves.toEqual({ success: true });
    expect(capturedHeaders.get('Authorization')).toBe('Bearer memory_credential');
    expect(capturedHeaders.get('X-Tenant-Id')).toBe('tenant_123');
    expect(capturedHeaders.get('X-Legal-Entity-Id')).toBe('legal_234');
    expect(capturedHeaders.get('X-Company-Id')).toBe('company_456');
    expect(capturedHeaders.get('X-Operating-Site-Id')).toBe('site_789');
    expect(capturedHeaders.get('X-Correlation-Id')).toBeTruthy();
  });

  it('forwards AbortSignal to fetch', async () => {
    const controller = new AbortController();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
    });
    await client.get('/cancelable', { signal: controller.signal });
    expect(vi.mocked(global.fetch).mock.calls[0][1]?.signal).toBe(controller.signal);
  });

  it('invalidates the session on 401 but leaves 403 as an authorization denial', async () => {
    const onUnauthorized = vi.fn();
    client.setOnUnauthorized(onUnauthorized);
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 403,
        statusText: 'Forbidden',
        json: async () => ({ code: 'FORBIDDEN', message: 'Denied' }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        json: async () => ({ code: 'UNAUTHORIZED', message: 'Expired' }),
      });

    await expect(client.get('/forbidden')).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).not.toHaveBeenCalled();
    await expect(client.get('/expired')).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });
});
