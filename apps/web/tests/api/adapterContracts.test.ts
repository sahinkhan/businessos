import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '../../src/api/client';
import { securityContext } from '../../src/api/securityContext';
import { HttpAuthAdapter } from '../../src/auth/authAdapter';
import { HttpPolicyAdapter } from '../../src/permissions/policyAdapter';
import { HttpScopeAdapter } from '../../src/scope/scopeAdapter';

describe('adapter URL contracts through the real ApiClient', () => {
  beforeEach(() => {
    apiClient.setCsrfTokenProvider(() => 'csrf');
    vi.restoreAllMocks();
  });

  it('composes the API prefix exactly once for auth, organization, and policy', async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'authenticated',
          principal: {
            id: 'principal',
            tenant_id: 'tenant',
            type: 'user',
            authentication_strength: 'oidc',
          },
          active_scope: { tenant_id: 'tenant' },
          expires_at: new Date(Date.now() + 60_000).toISOString(),
          csrf_token: 'csrf',
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          tenant_id: 'tenant',
          enterprise_groups: [],
          companies: [],
          operating_sites: [],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ allowed: false, reason: 'denied', matched_policy: null }),
      });

    await new HttpAuthAdapter().getSession();
    await new HttpScopeAdapter().fetchTenants();
    await new HttpPolicyAdapter().evaluateAuthorization({
      principalId: 'principal',
      tenantId: 'tenant',
      action: 'read',
      resourceType: 'invoice',
    });

    const urls = vi.mocked(global.fetch).mock.calls.map(([url]) => String(url));
    expect(urls).toEqual([
      '/api/v1/auth/session',
      '/api/v1/organization/hierarchy',
      '/api/v1/policy/authorize',
    ]);
    expect(urls.every((url) => !url.includes('/api/api/'))).toBe(true);
  });

  it('does not cache a policy response from an obsolete security generation', async () => {
    let resolve!: (response: Response) => void;
    global.fetch = vi.fn(() => new Promise<Response>((done) => (resolve = done))) as typeof fetch;
    const adapter = new HttpPolicyAdapter();
    const context = {
      principalId: 'principal-a',
      tenantId: 'tenant-a',
      action: 'read',
      resourceType: 'invoice',
    };
    const pending = adapter.evaluateAuthorization(context);
    securityContext.advance();
    resolve(
      new Response(JSON.stringify({ allowed: true, reason: 'stale', matched_policy: 'read' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    );
    await pending;
    expect(adapter.getCachedAuthorization('read', 'invoice', context)).toBeNull();
  });
});
