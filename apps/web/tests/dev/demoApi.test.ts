// @vitest-environment node
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createServer, type ViteDevServer } from 'vite';
import type { AddressInfo } from 'node:net';
import { spawnSync } from 'node:child_process';
import { demoApiPlugin } from '../../dev/demoApi';

const PASSWORD = 'test-only-password';
let server: ViteDevServer;
let base: string;

async function signIn(email: string, password = PASSWORD) {
  const response = await fetch(`${base}/api/dev/demo-login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  return { response, cookie: response.headers.get('set-cookie')?.split(';')[0] ?? '' };
}

describe('local demo server boundary', () => {
  beforeAll(async () => {
    server = await createServer({
      configFile: false,
      plugins: [demoApiPlugin(PASSWORD)],
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { host: '127.0.0.1', port: 0, strictPort: true },
    });
    await server.listen();
    base = `http://127.0.0.1:${(server.httpServer!.address() as AddressInfo).port}`;
  });

  afterAll(async () => {
    await server?.close();
  });

  it('rejects missing and invalid demo credentials', async () => {
    expect((await fetch(`${base}/api/v1/auth/session`)).status).toBe(401);
    expect((await signIn('admin@demo.businessos.test', 'wrong')).response.status).toBe(401);
    expect((await signIn('unknown@demo.businessos.test')).response.status).toBe(401);
  });

  it('requires a server session and CSRF for scoped policy and rotates on company change', async () => {
    const { response, cookie } = await signIn('admin@demo.businessos.test');
    expect(response.status).toBe(200);
    expect(response.headers.get('set-cookie')).toContain('HttpOnly');
    expect(cookie).toMatch(/^bos_demo_session=/);

    const sessionResponse = await fetch(`${base}/api/v1/auth/session`, {
      headers: { Cookie: cookie },
    });
    const session = await sessionResponse.json();
    expect(session.principal.email).toBe('admin@demo.businessos.test');
    const policyUrl = `${base}/api/v1/policy/authorize`;
    const policyBody = JSON.stringify({ action: 'read', resource_type: 'system.settings' });
    expect(
      (await fetch(policyUrl, { method: 'POST', headers: { Cookie: cookie }, body: policyBody }))
        .status
    ).toBe(403);
    const headers = { Cookie: cookie, 'X-CSRF-Token': session.csrf_token };
    expect(
      (await (await fetch(policyUrl, { method: 'POST', headers, body: policyBody })).json()).allowed
    ).toBe(true);
    expect(
      (
        await (
          await fetch(policyUrl, {
            method: 'POST',
            headers,
            body: JSON.stringify({ action: 'delete', resource_type: 'system.settings' }),
          })
        ).json()
      ).allowed
    ).toBe(false);

    const switchResponse = await fetch(`${base}/api/v1/organization/active-scope`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        tenant_id: '00000000-0000-4000-8000-000000000101',
        enterprise_group_id: '00000000-0000-4000-8000-000000000102',
        company_id: '00000000-0000-4000-8000-000000000105',
        operating_site_id: '00000000-0000-4000-8000-000000000106',
      }),
    });
    expect(switchResponse.status).toBe(200);
    expect(
      (await fetch(`${base}/api/v1/auth/session`, { headers: { Cookie: cookie } })).status
    ).toBe(401);
    const rotatedCookie = switchResponse.headers.get('set-cookie')?.split(';')[0] ?? '';
    const rotatedSession = await (
      await fetch(`${base}/api/v1/auth/session`, { headers: { Cookie: rotatedCookie } })
    ).json();
    expect(rotatedSession.active_scope.company_id).toBe('00000000-0000-4000-8000-000000000105');
    expect(rotatedSession.csrf_token).not.toBe(session.csrf_token);
  });

  it('keeps the viewer denied on settings', async () => {
    const { cookie } = await signIn('viewer@demo.businessos.test');
    const session = await (
      await fetch(`${base}/api/v1/auth/session`, { headers: { Cookie: cookie } })
    ).json();
    const decision = await fetch(`${base}/api/v1/policy/authorize`, {
      method: 'POST',
      headers: { Cookie: cookie, 'X-CSRF-Token': session.csrf_token },
      body: JSON.stringify({ action: 'read', resource_type: 'system.settings' }),
    });
    expect((await decision.json()).allowed).toBe(false);
  });

  it('refuses demo authentication in production mode', () => {
    const previous = process.env.NODE_ENV;
    process.env.NODE_ENV = 'production';
    try {
      expect(() => demoApiPlugin(PASSWORD)).toThrow('unavailable outside development');
    } finally {
      if (previous === undefined) delete process.env.NODE_ENV;
      else process.env.NODE_ENV = previous;
    }
    for (const environment of [
      { NODE_ENV: 'production', BOS_ENVIRONMENT: 'development' },
      { NODE_ENV: 'development', BOS_ENVIRONMENT: 'production' },
    ]) {
      const result = spawnSync(process.execPath, ['scripts/run-demo.mjs'], {
        cwd: process.cwd(),
        env: { ...process.env, ...environment },
        encoding: 'utf8',
        timeout: 10000,
      });
      expect(result.status).not.toBe(0);
      expect(result.stderr).toContain('available only in a development environment');
    }
  });
});
