import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from '../../src/auth/AuthContext';
import { HttpAuthAdapter } from '../../src/auth/authAdapter';
import { ScopeProvider, useScope } from '../../src/scope/ScopeContext';
import { HttpScopeAdapter } from '../../src/scope/scopeAdapter';
import { TEST_SESSION } from '../fixtures/security';

const SecurityControls = () => {
  const auth = useAuth();
  const scope = useScope();
  return (
    <>
      <span data-testid="auth-status">{auth.status}</span>
      <span data-testid="principal">{auth.session?.principal.id ?? 'none'}</span>
      <span data-testid="scope-status">{scope.status}</span>
      <span data-testid="company">{scope.scope?.companyId ?? 'none'}</span>
      <span data-testid="company-name">{scope.scope?.companyName ?? 'none'}</span>
      <span data-testid="csrf">{auth.session?.csrfToken ?? 'none'}</span>
      <span data-testid="error">{scope.error ?? auth.error ?? 'none'}</span>
      <button onClick={() => void scope.setCompany('company_two')}>Select B</button>
      <button onClick={() => void scope.setCompany('company_three')}>Select C</button>
      <button onClick={() => void auth.logout()}>Logout</button>
    </>
  );
};

const response = (payload: unknown, status = 200) =>
  new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

function sessionProjection(company: string, csrf: string) {
  return {
    status: 'authenticated',
    principal: {
      id: TEST_SESSION.principal.id,
      tenant_id: TEST_SESSION.principal.tenantId,
      type: TEST_SESSION.principal.type,
      authentication_strength: TEST_SESSION.principal.authenticationStrength,
    },
    active_scope: {
      tenant_id: 'tenant_one',
      enterprise_group_id: 'group_one',
      legal_entity_id: company,
      company_id: company,
      operating_site_id: 'site_one',
    },
    csrf_token: csrf,
    expires_at: new Date(TEST_SESSION.expiresAt * 1000).toISOString(),
  };
}

function scopeProjection(company: string, csrf: string) {
  return {
    valid: true,
    scope: {
      tenant_id: 'tenant_one',
      enterprise_group_id: 'group_one',
      legal_entity_id: company,
      company_id: company,
      operating_site_id: 'site_one',
    },
    csrf_token: csrf,
    expires_at: new Date(TEST_SESSION.expiresAt * 1000).toISOString(),
  };
}

function mount() {
  render(
    <AuthProvider initialSession={TEST_SESSION} adapter={new HttpAuthAdapter()}>
      <ScopeProvider adapter={new HttpScopeAdapter()}>
        <SecurityControls />
      </ScopeProvider>
    </AuthProvider>
  );
}

function hierarchy() {
  return {
    tenant_id: 'tenant_one',
    enterprise_groups: [{ id: 'group_one', name: 'Group One', code: 'G1' }],
    companies: [
      { id: 'company_one', name: 'Company One', code: 'C1' },
      { id: 'company_two', name: 'Company Two', code: 'C2' },
      { id: 'company_three', name: 'Company Three', code: 'C3' },
    ],
    operating_sites: [{ id: 'site_one', name: 'Site One', code: 'S1' }],
  };
}

describe('authoritative security snapshot recovery', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('reconciles a scope and CSRF token after an ambiguous 403 mutation', async () => {
    let company = 'company_one';
    let csrf = TEST_SESSION.csrfToken;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/organization/hierarchy')) return response(hierarchy());
        if (url.endsWith('/auth/session')) return response(sessionProjection(company, csrf));
        if (url.endsWith('/organization/active-scope')) {
          const selection = JSON.parse(String(init?.body)) as { company_id?: string };
          if (selection.company_id === 'company_two') {
            company = 'company_two';
            csrf = 'csrf-b';
            return response({ code: 'conflict', message: 'Mutation outcome is ambiguous' }, 403);
          }
          return response(scopeProjection(company, csrf));
        }
        throw new Error(`Unexpected request: ${url}`);
      })
    );

    mount();
    await waitFor(() => expect(screen.getByTestId('scope-status')).toHaveTextContent('ready'));
    fireEvent.click(screen.getByText('Select B'));
    await waitFor(() => expect(screen.getByTestId('error')).toHaveTextContent('ambiguous'));
    expect(screen.getByTestId('company')).toHaveTextContent('company_two');
    expect(screen.getByTestId('company-name')).toHaveTextContent('Company Two');
    expect(screen.getByTestId('csrf')).toHaveTextContent('csrf-b');
  });

  it('keeps the newer queued scope authoritative after reconciling an older failure', async () => {
    let company = 'company_one';
    let csrf = TEST_SESSION.csrfToken;
    let releaseB!: () => void;
    let releaseSession!: () => void;
    let sessionRequested!: () => void;
    const sessionRequestStarted = new Promise<void>((resolve) => {
      sessionRequested = resolve;
    });
    let delaySession = true;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/organization/hierarchy')) return response(hierarchy());
        if (url.endsWith('/auth/session')) {
          if (delaySession) {
            delaySession = false;
            sessionRequested();
            return new Promise<Response>((resolve) => {
              releaseSession = () => resolve(response(sessionProjection(company, csrf)));
            });
          }
          return response(sessionProjection(company, csrf));
        }
        if (url.endsWith('/organization/active-scope')) {
          const selection = JSON.parse(String(init?.body)) as { company_id?: string };
          if (selection.company_id === 'company_two') {
            return new Promise<Response>((resolve) => {
              releaseB = () => {
                company = 'company_two';
                csrf = 'csrf-b';
                resolve(response({ code: 'conflict', message: 'B response failed' }, 403));
              };
            });
          }
          if (selection.company_id === 'company_three') {
            expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('csrf-b');
            company = 'company_three';
            csrf = 'csrf-c';
          }
          return response(scopeProjection(company, csrf));
        }
        throw new Error(`Unexpected request: ${url}`);
      })
    );

    mount();
    await waitFor(() => expect(screen.getByTestId('scope-status')).toHaveTextContent('ready'));
    fireEvent.click(screen.getByText('Select B'));
    await act(async () => releaseB());
    await act(async () => sessionRequestStarted);
    fireEvent.click(screen.getByText('Select C'));
    await act(async () => releaseSession());
    await waitFor(() => expect(screen.getByTestId('company')).toHaveTextContent('company_three'));
    expect(screen.getByTestId('csrf')).toHaveTextContent('csrf-c');
  });

  it('converges to unauthenticated when failed-scope reconciliation returns 401', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/organization/hierarchy')) return response(hierarchy());
        if (url.endsWith('/auth/session')) return response({ code: 'unauthenticated' }, 401);
        if (url.endsWith('/organization/active-scope')) {
          const selection = JSON.parse(String(init?.body)) as { company_id?: string };
          return selection.company_id === 'company_two'
            ? response({ code: 'conflict', message: 'Unknown mutation outcome' }, 403)
            : response(scopeProjection('company_one', TEST_SESSION.csrfToken));
        }
        throw new Error(`Unexpected request: ${url}`);
      })
    );

    mount();
    await waitFor(() => expect(screen.getByTestId('scope-status')).toHaveTextContent('ready'));
    fireEvent.click(screen.getByText('Select B'));
    await waitFor(() => expect(screen.getByTestId('principal')).toHaveTextContent('none'));
    expect(screen.getByTestId('company')).toHaveTextContent('none');
    expect(screen.getByTestId('auth-status')).toHaveTextContent('unauthenticated');
  });

  it.each([
    ['500', () => response({ code: 'unavailable', message: 'Session unavailable' }, 500)],
    ['network', () => Promise.reject(new TypeError('Failed to fetch'))],
  ])(
    'fails closed when %s prevents reconciliation after an ambiguous mutation',
    async (_label, fail) => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
          const url = String(input);
          if (url.endsWith('/organization/hierarchy')) return response(hierarchy());
          if (url.endsWith('/auth/session')) return fail();
          if (url.endsWith('/organization/active-scope')) {
            const selection = JSON.parse(String(init?.body)) as { company_id?: string };
            return selection.company_id === 'company_two'
              ? response({ code: 'conflict', message: 'Unknown mutation outcome' }, 500)
              : response(scopeProjection('company_one', TEST_SESSION.csrfToken));
          }
          throw new Error(`Unexpected request: ${url}`);
        })
      );

      mount();
      await waitFor(() => expect(screen.getByTestId('scope-status')).toHaveTextContent('ready'));
      fireEvent.click(screen.getByText('Select B'));
      await waitFor(() =>
        expect(screen.getByTestId('auth-status')).toHaveTextContent('service_unavailable')
      );
      expect(screen.getByTestId('principal')).toHaveTextContent('none');
      expect(screen.getByTestId('company')).toHaveTextContent('none');
      expect(screen.getByTestId('scope-status')).toHaveTextContent('unavailable');
    }
  );

  it('reconciles stale CSRF once, revokes the server session, and then clears local auth', async () => {
    let active = true;
    const logoutTokens: Array<string | null> = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/organization/hierarchy')) return response(hierarchy());
        if (url.endsWith('/organization/active-scope')) {
          return response(scopeProjection('company_one', TEST_SESSION.csrfToken));
        }
        if (url.endsWith('/auth/session')) {
          return active
            ? response(sessionProjection('company_two', 'authoritative-csrf-b'))
            : response({ code: 'unauthenticated' }, 401);
        }
        if (url.endsWith('/auth/logout')) {
          const token = new Headers(init?.headers).get('X-CSRF-Token');
          logoutTokens.push(token);
          if (token !== 'authoritative-csrf-b') {
            return response({ code: 'invalid_csrf', message: 'CSRF validation failed' }, 403);
          }
          active = false;
          return new Response(null, { status: 204 });
        }
        throw new Error(`Unexpected request: ${url}`);
      })
    );

    mount();
    await waitFor(() => expect(screen.getByTestId('scope-status')).toHaveTextContent('ready'));
    fireEvent.click(screen.getByText('Logout'));
    await waitFor(() => expect(screen.getByTestId('principal')).toHaveTextContent('none'));
    expect(logoutTokens).toEqual([TEST_SESSION.csrfToken, 'authoritative-csrf-b']);
    expect(active).toBe(false);
    expect(screen.getByTestId('auth-status')).toHaveTextContent('unauthenticated');
  });

  it('lets queued logout win after failed scope reconciliation without auth resurrection', async () => {
    let company = 'company_one';
    let csrf = TEST_SESSION.csrfToken;
    let active = true;
    let releaseB!: () => void;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/organization/hierarchy')) return response(hierarchy());
        if (url.endsWith('/auth/session')) {
          return active
            ? response(sessionProjection(company, csrf))
            : response({ code: 'unauthenticated' }, 401);
        }
        if (url.endsWith('/organization/active-scope')) {
          const selection = JSON.parse(String(init?.body)) as { company_id?: string };
          if (selection.company_id === 'company_two') {
            return new Promise<Response>((resolve) => {
              releaseB = () => {
                company = 'company_two';
                csrf = 'csrf-b';
                resolve(response({ code: 'conflict', message: 'Unknown mutation outcome' }, 403));
              };
            });
          }
          return response(scopeProjection(company, csrf));
        }
        if (url.endsWith('/auth/logout')) {
          expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('csrf-b');
          active = false;
          return new Response(null, { status: 204 });
        }
        throw new Error(`Unexpected request: ${url}`);
      })
    );

    mount();
    await waitFor(() => expect(screen.getByTestId('scope-status')).toHaveTextContent('ready'));
    fireEvent.click(screen.getByText('Select B'));
    fireEvent.click(screen.getByText('Logout'));
    await act(async () => releaseB());
    await waitFor(() => expect(screen.getByTestId('principal')).toHaveTextContent('none'));
    expect(active).toBe(false);
    expect(screen.getByTestId('company')).toHaveTextContent('none');
  });

  it('accepts confirmed session absence after stale-CSRF logout', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/organization/hierarchy')) return response(hierarchy());
        if (url.endsWith('/organization/active-scope')) {
          return response(scopeProjection('company_one', TEST_SESSION.csrfToken));
        }
        if (url.endsWith('/auth/logout')) {
          return response({ code: 'invalid_csrf', message: 'CSRF validation failed' }, 403);
        }
        if (url.endsWith('/auth/session')) return response({ code: 'unauthenticated' }, 401);
        throw new Error(`Unexpected request: ${url}`);
      })
    );

    mount();
    await waitFor(() => expect(screen.getByTestId('scope-status')).toHaveTextContent('ready'));
    fireEvent.click(screen.getByText('Logout'));
    await waitFor(() => expect(screen.getByTestId('principal')).toHaveTextContent('none'));
    expect(screen.getByTestId('auth-status')).toHaveTextContent('unauthenticated');
  });

  it('reconciles the live authoritative snapshot after an ambiguous logout 500', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/organization/hierarchy')) return response(hierarchy());
        if (url.endsWith('/organization/active-scope')) {
          return response(scopeProjection('company_one', TEST_SESSION.csrfToken));
        }
        if (url.endsWith('/auth/logout')) {
          return response({ code: 'unavailable', message: 'Logout outcome is unknown' }, 500);
        }
        if (url.endsWith('/auth/session')) {
          return response(sessionProjection('company_two', 'authoritative-csrf-b'));
        }
        throw new Error(`Unexpected request: ${url}`);
      })
    );

    mount();
    await waitFor(() => expect(screen.getByTestId('scope-status')).toHaveTextContent('ready'));
    fireEvent.click(screen.getByText('Logout'));
    await waitFor(() =>
      expect(screen.getByTestId('auth-status')).toHaveTextContent('service_unavailable')
    );
    expect(screen.getByTestId('principal')).toHaveTextContent(TEST_SESSION.principal.id);
    expect(screen.getByTestId('company')).toHaveTextContent('company_two');
    expect(screen.getByTestId('csrf')).toHaveTextContent('authoritative-csrf-b');
  });

  it.each([
    ['logout 500', 'logout'],
    ['logout network failure', 'network'],
    ['reconciliation 500', 'reconcile'],
  ])('retains local authentication on %s', async (_label, failure) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/organization/hierarchy')) return response(hierarchy());
        if (url.endsWith('/organization/active-scope')) {
          return response(scopeProjection('company_one', TEST_SESSION.csrfToken));
        }
        if (url.endsWith('/auth/logout')) {
          if (failure === 'network') throw new TypeError('Failed to fetch');
          if (failure === 'logout') {
            return response({ code: 'unavailable', message: 'Logout unavailable' }, 500);
          }
          return response({ code: 'invalid_csrf', message: 'CSRF validation failed' }, 403);
        }
        if (url.endsWith('/auth/session')) {
          return response({ code: 'unavailable', message: 'Session unavailable' }, 500);
        }
        throw new Error(`Unexpected request: ${url}`);
      })
    );

    mount();
    await waitFor(() => expect(screen.getByTestId('scope-status')).toHaveTextContent('ready'));
    fireEvent.click(screen.getByText('Logout'));
    await waitFor(() =>
      expect(screen.getByTestId('auth-status')).toHaveTextContent('service_unavailable')
    );
    expect(screen.getByTestId('principal')).toHaveTextContent(TEST_SESSION.principal.id);
  });
});
