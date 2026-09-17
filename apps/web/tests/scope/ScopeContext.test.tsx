import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '../../src/api/queryCache';
import { AuthProvider } from '../../src/auth/AuthContext';
import { ScopeProvider, useScope } from '../../src/scope/ScopeContext';
import { HttpScopeAdapter, ScopeAdapter } from '../../src/scope/scopeAdapter';
import { MockScopeAdapter } from '../../src/scope/mockScopeAdapter';
import { TEST_SESSION, TEST_TENANTS, TEST_USER } from '../fixtures/security';

const Consumer = () => {
  const { scope, status, error, setCompany, setTenant } = useScope();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="tenant">{scope?.tenantName ?? 'none'}</span>
      <span data-testid="company">{scope?.companyName ?? 'none'}</span>
      <span data-testid="error">{error ?? 'none'}</span>
      <button onClick={() => void setCompany('company_two')}>Company two</button>
      <button onClick={() => void setCompany('rejected_company')}>Rejected</button>
      <button onClick={() => void setTenant('tenant_two')}>Tenant two</button>
    </div>
  );
};

const renderScope = (adapter: ScopeAdapter) =>
  render(
    <AuthProvider initialUser={TEST_USER} initialSession={TEST_SESSION}>
      <ScopeProvider adapter={adapter}>
        <Consumer />
      </ScopeProvider>
    </AuthProvider>
  );

describe('backend-authoritative scope boundary', () => {
  beforeEach(() => {
    localStorage.clear();
    queryCache.clear();
    vi.restoreAllMocks();
  });

  it('establishes and switches only backend-validated scope and clears cached data', async () => {
    renderScope(new MockScopeAdapter(TEST_TENANTS));
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('ready'));
    expect(screen.getByTestId('company')).toHaveTextContent('Company One');

    queryCache.set('scope-data', { secret: true });
    fireEvent.click(screen.getByText('Company two'));
    await waitFor(() => expect(screen.getByTestId('company')).toHaveTextContent('Company Two'));
    expect(queryCache.size()).toBe(0);

    fireEvent.click(screen.getByText('Tenant two'));
    await waitFor(() => expect(screen.getByTestId('tenant')).toHaveTextContent('Tenant Two'));
  });

  it('does not apply a backend-rejected company', async () => {
    renderScope(new MockScopeAdapter(TEST_TENANTS));
    await waitFor(() => expect(screen.getByTestId('company')).toHaveTextContent('Company One'));
    fireEvent.click(screen.getByText('Rejected'));
    await waitFor(() => expect(screen.getByTestId('error')).toHaveTextContent('Company rejected'));
    expect(screen.getByTestId('company')).toHaveTextContent('Company One');
  });

  it('validates an untrusted local preference before it can become active', async () => {
    localStorage.setItem(
      'businessos.scope.preference',
      JSON.stringify({ tenant_id: 'attacker_tenant', company_id: 'attacker_company' })
    );
    renderScope(new MockScopeAdapter(TEST_TENANTS));
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('ready'));
    expect(screen.getByTestId('tenant')).toHaveTextContent('Tenant One');
    expect(screen.getByTestId('tenant')).not.toHaveTextContent('attacker');
  });

  it('shows unavailable state when the production backend cannot establish scope', async () => {
    const adapter: ScopeAdapter = {
      fetchTenants: vi.fn().mockRejectedValue(new Error('scope backend unavailable')),
      selectActiveScope: vi.fn(),
      validateScope: vi.fn(),
    };
    renderScope(adapter);
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unavailable'));
    expect(screen.getByTestId('tenant')).toHaveTextContent('none');
  });

  it('production adapter propagates backend failure without fixture fallback', async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(new HttpScopeAdapter().fetchTenants()).rejects.toThrow('Failed to fetch');
  });
});
