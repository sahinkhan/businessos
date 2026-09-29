import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../../src/api/client';
import { queryCache } from '../../src/api/queryCache';
import { securityContext } from '../../src/api/securityContext';

afterEach(() => {
  vi.unstubAllGlobals();
  securityContext.transition(null);
});

describe('security context isolation', () => {
  it('aborts an old company response and clears its cached data on transition', async () => {
    securityContext.transition({
      sessionId: 'session-a',
      userId: 'user-a',
      tenantId: 'tenant-a',
      companyId: 'company-x',
      siteId: null,
      csrfToken: 'csrf-a',
    });
    const oldKey = securityContext.key();
    queryCache.set(`${oldKey}:ledger`, { company: 'X' });
    let finish!: (response: Response) => void;
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          })
      )
    );
    const pending = new ApiClient().get('/v1/data');
    securityContext.transition({
      sessionId: 'session-a',
      userId: 'user-a',
      tenantId: 'tenant-a',
      companyId: 'company-y',
      siteId: null,
      csrfToken: 'csrf-b',
    });
    expect(queryCache.get(`${oldKey}:ledger`)).toBeNull();
    finish(new Response(JSON.stringify({ company: 'X' }), { status: 200 }));
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(securityContext.key()).not.toBe(oldKey);
  });

  it('sends only the server session CSRF value on mutations and never a bearer token', async () => {
    securityContext.transition({
      sessionId: 'session-a',
      userId: 'user-a',
      tenantId: 'tenant-a',
      companyId: 'company-x',
      siteId: null,
      csrfToken: 'server-csrf',
    });
    const fetcher = vi.fn(async (_url: URL, request: RequestInit) => {
      const headers = new Headers(request.headers);
      expect(headers.get('X-CSRF-Token')).toBe('server-csrf');
      expect(headers.get('Authorization')).toBeNull();
      expect(request.credentials).toBe('same-origin');
      return new Response('{}', { status: 200 });
    });
    vi.stubGlobal('fetch', fetcher);
    await new ApiClient().post('/v1/data', { value: 1 });
    expect(fetcher).toHaveBeenCalledOnce();
    await expect(new ApiClient('https://other.example').get('/v1/data')).rejects.toThrow(
      /same-origin/
    );
  });
});
