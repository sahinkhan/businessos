import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ApiClient } from '../../src/api/client';
import { ApiError } from '../../src/api/types';

describe('ApiClient Hardening', () => {
  let client: ApiClient;

  beforeEach(() => {
    client = new ApiClient('/api');
    vi.restoreAllMocks();
  });

  it('injects Authorization and Scope headers from registered providers', async () => {
    client.setTokenProvider(() => 'test_jwt_token');
    client.setScopeProvider(() => ({
      tenantId: 'tenant_123',
      companyId: 'cmp_456',
      siteId: 'site_789',
    }));

    let capturedHeaders: Record<string, string> = {};
    global.fetch = vi.fn().mockImplementation((_url, init) => {
      capturedHeaders = init.headers;
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ success: true }),
      });
    });

    const res = await client.get('/test-endpoint');
    expect(res).toEqual({ success: true });
    expect(capturedHeaders['Authorization']).toBe('Bearer test_jwt_token');
    expect(capturedHeaders['X-Tenant-Id']).toBe('tenant_123');
    expect(capturedHeaders['X-Company-Id']).toBe('cmp_456');
    expect(capturedHeaders['X-Operating-Site-Id']).toBe('site_789');
    expect(capturedHeaders['X-Correlation-Id']).toBeDefined();
  });

  it('triggers onUnauthorized callback on 401 response status', async () => {
    const onUnauthorized = vi.fn();
    client.setOnUnauthorized(onUnauthorized);

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
      json: () => Promise.resolve({ code: 'UNAUTHORIZED', message: 'Session expired' }),
    });

    await expect(client.get('/secure-resource')).rejects.toThrow(ApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });
});
