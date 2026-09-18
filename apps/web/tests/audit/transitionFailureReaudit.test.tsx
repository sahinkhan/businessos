import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from '../../src/auth/AuthContext';
import { HttpAuthAdapter } from '../../src/auth/authAdapter';
import { ScopeProvider, useScope } from '../../src/scope/ScopeContext';
import { HttpScopeAdapter } from '../../src/scope/scopeAdapter';
import { TEST_SESSION } from '../fixtures/security';

const Controls = () => {
  const { scope, status, error, setCompany } = useScope();
  const { session, logout } = useAuth();
  return (
    <>
      <span data-testid="scope-status">{status}</span>
      <span data-testid="company">{scope?.companyId}</span>
      <span data-testid="csrf">{session?.csrfToken}</span>
      <span data-testid="error">{error}</span>
      <button onClick={() => void setCompany('company_two')}>Select B</button>
      <button onClick={() => void setCompany('company_one')}>Select A</button>
      <button onClick={() => void logout().catch(() => undefined)}>Logout</button>
    </>
  );
};

function backendBoundary() {
  let company = 'company_one';
  let csrf = TEST_SESSION.csrfToken;
  let revoked = false;
  let logoutCsrf: string | null = null;
  let releaseB!: () => void;
  const response = (payload: unknown, status = 200) =>
    new Response(JSON.stringify(payload), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  const projection = () => ({
    valid: true,
    scope: {
      tenant_id: 'tenant_one',
      enterprise_group_id: 'group_one',
      company_id: company,
      operating_site_id: 'site_one',
    },
    csrf_token: csrf,
    expires_at: new Date(TEST_SESSION.expiresAt * 1000).toISOString(),
  });
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith('/organization/hierarchy')) {
      return response({
        tenant_id: 'tenant_one',
        enterprise_groups: [{ id: 'group_one', name: 'Group One', code: 'G1' }],
        companies: [
          { id: 'company_one', name: 'Company One', code: 'C1' },
          { id: 'company_two', name: 'Company Two', code: 'C2' },
        ],
        operating_sites: [{ id: 'site_one', name: 'Site One', code: 'S1' }],
      });
    }
    if (url.endsWith('/organization/active-scope')) {
      const selection = JSON.parse(String(init?.body)) as { company_id?: string };
      if (selection.company_id === 'company_two') {
        return new Promise<Response>((resolve) => {
          releaseB = () => {
            company = 'company_two';
            csrf = 'rotated-csrf-b';
            resolve(response(projection()));
          };
        });
      }
      if (selection.company_id === 'company_one') {
        return response({ code: 'forbidden', message: 'Company A is no longer authorized' }, 403);
      }
      csrf = 'initial-csrf-a';
      return response(projection());
    }
    if (url.endsWith('/auth/logout')) {
      logoutCsrf = new Headers(init?.headers).get('X-CSRF-Token');
      if (logoutCsrf !== csrf) {
        return response({ code: 'invalid_csrf', message: 'CSRF validation failed' }, 403);
      }
      revoked = true;
      return new Response(null, { status: 204 });
    }
    throw new Error(`Unexpected audit request: ${url}`);
  });
  return {
    fetch,
    releaseB: () => releaseB(),
    snapshot: () => ({ company, csrf, revoked, logoutCsrf }),
  };
}

function mount() {
  render(
    <AuthProvider initialSession={TEST_SESSION} adapter={new HttpAuthAdapter()}>
      <ScopeProvider adapter={new HttpScopeAdapter()}>
        <Controls />
      </ScopeProvider>
    </AuthProvider>
  );
}

describe('independent security-transition failure re-audit', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('keeps the last committed server scope when the queued request returns HTTP 403', async () => {
    const server = backendBoundary();
    vi.stubGlobal('fetch', server.fetch);
    mount();
    await waitFor(() => expect(screen.getByTestId('scope-status')).toHaveTextContent('ready'));
    fireEvent.click(screen.getByText('Select B'));
    fireEvent.click(screen.getByText('Select A'));
    await act(async () => server.releaseB());
    await waitFor(() =>
      expect(screen.getByTestId('error')).toHaveTextContent('no longer authorized')
    );
    expect.soft(screen.getByTestId('company')).toHaveTextContent(server.snapshot().company);
    expect(screen.getByTestId('csrf')).toHaveTextContent(server.snapshot().csrf);
  });

  it('uses the rotated CSRF token for logout queued behind a scope mutation', async () => {
    const server = backendBoundary();
    vi.stubGlobal('fetch', server.fetch);
    mount();
    await waitFor(() => expect(screen.getByTestId('scope-status')).toHaveTextContent('ready'));
    fireEvent.click(screen.getByText('Select B'));
    fireEvent.click(screen.getByText('Logout'));
    await act(async () => server.releaseB());
    await waitFor(() => expect(server.snapshot().logoutCsrf).not.toBeNull());
    expect.soft(server.snapshot().logoutCsrf).toBe(server.snapshot().csrf);
    expect(server.snapshot().revoked).toBe(true);
  });
});
