import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from '../../src/auth/AuthContext';
import { HttpAuthAdapter } from '../../src/auth/authAdapter';
import { AuthAdapter } from '../../src/auth/authAdapter';
import { Modal } from '../../src/components/overlays/Modal';
import { ScopeProvider } from '../../src/scope/ScopeContext';
import { MockScopeAdapter } from '../../src/scope/mockScopeAdapter';
import { HttpScopeAdapter, ScopeAdapter } from '../../src/scope/scopeAdapter';
import { TEST_SESSION, TEST_TENANTS } from '../fixtures/security';

const AuthState = () => {
  const { isLoading, isAuthenticated } = useAuth();
  return (
    <span data-testid="auth-state">
      {String(isLoading)}:{String(isAuthenticated)}
    </span>
  );
};

const SecurityControls = () => {
  const { session, updateSessionSecurity, reloadSession, logout } = useAuth();
  return (
    <>
      <button
        onClick={() =>
          session &&
          updateSessionSecurity(session.activeScope, 'same-principal-csrf', session.expiresAt)
        }
      >
        Rotate security
      </button>
      <button onClick={() => void reloadSession()}>Replace principal</button>
      <button onClick={() => void logout()}>Log out</button>
    </>
  );
};

describe('independent Phase 4.5 re-audit', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('finishes unauthenticated bootstrap after a real-client HTTP 401', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        json: async () => ({ code: 'unauthenticated', message: 'Authentication required' }),
      })
    );
    await act(async () => {
      render(
        <AuthProvider adapter={new HttpAuthAdapter()}>
          <AuthState />
        </AuthProvider>
      );
    });
    expect(screen.getByTestId('auth-state')).toHaveTextContent('false:false');
  });

  it('establishes scope once when the backend returns session rotation fields', async () => {
    const mock = new MockScopeAdapter(TEST_TENANTS);
    const fetchTenants = vi
      .fn()
      .mockResolvedValueOnce(TEST_TENANTS)
      // Hold any unexpected second initialization so a regression cannot spin forever.
      .mockImplementation(() => new Promise(() => {}));
    const selectActiveScope = vi.fn(async () => ({
      ...(await mock.selectActiveScope({ tenant_id: 'tenant_one' })),
      csrfToken: 'rotated-csrf',
      expiresAt: TEST_SESSION.expiresAt,
    }));
    const adapter: ScopeAdapter = {
      fetchTenants,
      selectActiveScope,
      validateScope: async () => true,
    };
    await act(async () => {
      render(
        <AuthProvider initialSession={TEST_SESSION}>
          <ScopeProvider adapter={adapter}>
            <AuthState />
          </ScopeProvider>
        </AuthProvider>
      );
    });
    expect(selectActiveScope).toHaveBeenCalledTimes(1);
    expect(fetchTenants).toHaveBeenCalledTimes(1);
  });

  it('bounds scope initialization across security rotation, principal replacement, and logout', async () => {
    const replacement = {
      ...TEST_SESSION,
      principal: { ...TEST_SESSION.principal, id: 'replacement-principal' },
    };
    const authAdapter: AuthAdapter = {
      getSession: vi.fn().mockResolvedValue(replacement),
      startLogin: vi.fn(),
      logout: vi.fn(),
    };
    const mock = new MockScopeAdapter(TEST_TENANTS);
    const scopeAdapter: ScopeAdapter = {
      fetchTenants: vi.fn().mockResolvedValue(TEST_TENANTS),
      selectActiveScope: vi.fn((selection) => mock.selectActiveScope(selection)),
      validateScope: vi.fn().mockResolvedValue(true),
    };
    render(
      <AuthProvider adapter={authAdapter} initialSession={TEST_SESSION}>
        <ScopeProvider adapter={scopeAdapter}>
          <SecurityControls />
        </ScopeProvider>
      </AuthProvider>
    );
    await waitFor(() => expect(scopeAdapter.fetchTenants).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByText('Rotate security'));
    await Promise.resolve();
    expect(scopeAdapter.fetchTenants).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText('Replace principal'));
    await waitFor(() => expect(scopeAdapter.fetchTenants).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByText('Log out'));
    await waitFor(() => expect(authAdapter.logout).toHaveBeenCalledTimes(1));
    expect(scopeAdapter.fetchTenants).toHaveBeenCalledTimes(2);
  });

  it('preserves readable active-scope names from the fetched hierarchy', async () => {
    const hierarchy = {
      tenant_id: 'tenant-one',
      enterprise_groups: [{ id: 'group-one', name: 'Group One', code: 'G1' }],
      companies: [{ id: 'company-one', name: 'Company One', code: 'C1' }],
      operating_sites: [{ id: 'site-one', name: 'Site One', code: 'S1' }],
    };
    const selection = {
      tenant_id: 'tenant-one',
      enterprise_group_id: 'group-one',
      company_id: 'company-one',
      operating_site_id: 'site-one',
    };
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce({ ok: true, status: 200, json: async () => hierarchy })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({
            valid: true,
            scope: selection,
            csrf_token: 'rotated-csrf',
            expires_at: new Date(TEST_SESSION.expiresAt * 1000).toISOString(),
          }),
        })
    );
    const adapter = new HttpScopeAdapter();
    const tenants = await adapter.fetchTenants();
    const selected = await adapter.selectActiveScope(selection);

    expect(tenants[0].groups[0].companies[0].name).toBe('Company One');
    expect(selected.valid).toBe(true);
    // ScopeSwitcher renders these exact fields in its persistent context indicator.
    expect(selected.scope).toMatchObject({ companyName: 'Company One', siteName: 'Site One' });
  });

  it('keeps focus in a controlled modal field while the parent rerenders', () => {
    const Editor = () => {
      const [open, setOpen] = useState(true);
      const [name, setName] = useState('');
      return (
        <Modal isOpen={open} onClose={() => setOpen(false)} title="Edit record">
          <input aria-label="Name" value={name} onChange={(event) => setName(event.target.value)} />
        </Modal>
      );
    };
    render(<Editor />);
    const input = screen.getByRole('textbox', { name: 'Name' });
    input.focus();
    fireEvent.change(input, { target: { value: 'A' } });
    expect(input).toHaveValue('A');
    expect(input).toHaveFocus();
  });
});
