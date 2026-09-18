import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '../../src/api/queryCache';
import { AuthProvider } from '../../src/auth/AuthContext';
import { ScopeProvider, useScope } from '../../src/scope/ScopeContext';
import { HttpScopeAdapter, ScopeAdapter } from '../../src/scope/scopeAdapter';
import { MockScopeAdapter } from '../../src/scope/mockScopeAdapter';
import { TEST_SESSION, TEST_TENANTS, TEST_USER } from '../fixtures/security';

const Consumer = () => {
  const { scope, status, error, setCompany, setSite, setTenant } = useScope();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="tenant">{scope?.tenantName ?? 'none'}</span>
      <span data-testid="company">{scope?.companyName ?? 'none'}</span>
      <span data-testid="site">{scope?.siteName ?? 'none'}</span>
      <span data-testid="error">{error ?? 'none'}</span>
      <button onClick={() => void setCompany('company_two')}>Company two</button>
      <button onClick={() => void setCompany('company_one')}>Company one</button>
      <button onClick={() => void setCompany('rejected_company')}>Rejected</button>
      <button onClick={() => void setTenant('tenant_two')}>Tenant two</button>
      <button onClick={() => void setSite('site_two')}>Site two</button>
      <button onClick={() => void setSite('rejected_site')}>Rejected site</button>
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

  it('keeps scope selection idempotent and preserves site labels through switching and reload', async () => {
    const mock = new MockScopeAdapter(TEST_TENANTS);
    const adapter: ScopeAdapter = {
      fetchTenants: vi.fn(() => mock.fetchTenants()),
      selectActiveScope: vi.fn((selection) => mock.selectActiveScope(selection)),
      validateScope: vi.fn((scope) => mock.validateScope(scope)),
    };
    const first = renderScope(adapter);
    await waitFor(() => expect(screen.getByTestId('site')).toHaveTextContent('Site One'));
    expect(adapter.selectActiveScope).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText('Company one'));
    await Promise.resolve();
    expect(adapter.selectActiveScope).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText('Site two'));
    await waitFor(() => expect(screen.getByTestId('site')).toHaveTextContent('Site Two'));
    expect(adapter.selectActiveScope).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByText('Rejected site'));
    await waitFor(() =>
      expect(screen.getByTestId('error')).toHaveTextContent('Operating site rejected')
    );
    expect(screen.getByTestId('site')).toHaveTextContent('Site Two');
    expect(adapter.selectActiveScope).toHaveBeenCalledTimes(3);

    first.unmount();
    renderScope(adapter);
    await waitFor(() => expect(screen.getByTestId('site')).toHaveTextContent('Site Two'));
    expect(adapter.fetchTenants).toHaveBeenCalledTimes(2);
    expect(adapter.selectActiveScope).toHaveBeenCalledTimes(4);
  });

  it('does not apply a late scope response after a newer selection', async () => {
    class DelayedScopeAdapter extends MockScopeAdapter {
      private release: (() => void) | null = null;

      public override async selectActiveScope(selection: {
        tenant_id: string;
        company_id?: string;
      }) {
        if (selection.company_id !== 'company_two') return super.selectActiveScope(selection);
        return new Promise<Awaited<ReturnType<MockScopeAdapter['selectActiveScope']>>>(
          (resolve) => {
            this.release = () => void super.selectActiveScope(selection).then(resolve);
          }
        );
      }

      public releaseCompanyTwo(): void {
        this.release?.();
      }
    }

    const adapter = new DelayedScopeAdapter(TEST_TENANTS);
    renderScope(adapter);
    await waitFor(() => expect(screen.getByTestId('company')).toHaveTextContent('Company One'));
    fireEvent.click(screen.getByText('Company two'));
    fireEvent.click(screen.getByText('Company one'));
    expect(screen.getByTestId('status')).toHaveTextContent('switching');
    adapter.releaseCompanyTwo();
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('ready'));
    expect(screen.getByTestId('company')).toHaveTextContent('Company One');
  });

  it('serializes overlapping mutations and preserves the last accepted scope when the latest is rejected', async () => {
    const mock = new MockScopeAdapter(TEST_TENANTS);
    let releaseCompanyTwo!: () => void;
    const selectActiveScope = vi.fn((selection) => {
      if (selection.company_id === 'company_two') {
        return new Promise<Awaited<ReturnType<MockScopeAdapter['selectActiveScope']>>>(
          (resolve) => {
            releaseCompanyTwo = () => void mock.selectActiveScope(selection).then(resolve);
          }
        );
      }
      return mock.selectActiveScope(selection);
    });
    const adapter: ScopeAdapter = {
      fetchTenants: () => mock.fetchTenants(),
      selectActiveScope,
      validateScope: (scope) => mock.validateScope(scope),
    };
    renderScope(adapter);
    await waitFor(() => expect(screen.getByTestId('company')).toHaveTextContent('Company One'));

    fireEvent.click(screen.getByText('Company two'));
    fireEvent.click(screen.getByText('Rejected'));
    expect(selectActiveScope).toHaveBeenCalledTimes(2);
    queryCache.set('stale-scope-data', { secret: true });
    releaseCompanyTwo();

    await waitFor(() => expect(screen.getByTestId('company')).toHaveTextContent('Company Two'));
    expect(screen.getByTestId('error')).toHaveTextContent('Company rejected');
    expect(selectActiveScope).toHaveBeenCalledTimes(3);
    expect(queryCache.size()).toBe(0);
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
