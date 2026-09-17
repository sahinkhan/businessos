import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ScopeProvider, useScope } from '../../src/scope/ScopeContext';
import { MockScopeAdapter, CONTRACT_DEFAULT_TENANTS } from '../../src/scope/scopeAdapter';
import { queryCache } from '../../src/api/queryCache';

const TestScopeComponent = () => {
  const { scope, setTenant, setCompany, tenants } = useScope();
  return (
    <div>
      <div data-testid="tenant">{scope.tenantName}</div>
      <div data-testid="company">{scope.companyName}</div>
      <div data-testid="site">{scope.siteName}</div>
      <button onClick={() => setCompany('cmp_canada_ops')}>Switch to Canada</button>
      <button onClick={() => setTenant(tenants[1].id)}>Switch to APAC</button>
      <button onClick={() => setCompany('invalid_cmp')}>Switch to Invalid Company</button>
    </div>
  );
};

describe('Scope & Entity Isolation Foundation', () => {
  beforeEach(() => {
    localStorage.clear();
    queryCache.clear();
  });

  it('provides default active scope and permits switching entities', async () => {
    const adapter = new MockScopeAdapter(CONTRACT_DEFAULT_TENANTS);

    render(
      <ScopeProvider adapter={adapter}>
        <TestScopeComponent />
      </ScopeProvider>
    );

    expect(screen.getByTestId('tenant')).toHaveTextContent('Global Enterprise Holdings');
    expect(screen.getByTestId('company')).toHaveTextContent('US Technology Inc');

    // Populate cache with dummy data
    queryCache.set('tenant_data', { foo: 'bar' });
    expect(queryCache.get('tenant_data')).toEqual({ foo: 'bar' });

    // Switch company under same tenant
    fireEvent.click(screen.getByText('Switch to Canada'));
    await waitFor(() => {
      expect(screen.getByTestId('company')).toHaveTextContent('Canada Logistics Corp');
    });

    // Query cache should have been cleared on scope transition
    expect(queryCache.get('tenant_data')).toBeNull();

    // Switch tenant
    fireEvent.click(screen.getByText('Switch to APAC'));
    await waitFor(() => {
      expect(screen.getByTestId('tenant')).toHaveTextContent('APAC Retail Ventures');
      expect(screen.getByTestId('company')).toHaveTextContent('Singapore Trading Pte Ltd');
    });
  });

  it('safely handles stale or invalid scope in storage', async () => {
    localStorage.setItem(
      'businessos.active_scope',
      JSON.stringify({
        tenantId: 'non_existent_tenant',
        companyId: 'ghost_company',
        siteId: 'ghost_site',
      })
    );

    const adapter = new MockScopeAdapter(CONTRACT_DEFAULT_TENANTS);

    render(
      <ScopeProvider adapter={adapter}>
        <TestScopeComponent />
      </ScopeProvider>
    );

    // Stale scope must be reset safely to default valid hierarchy
    await waitFor(() => {
      expect(screen.getByTestId('tenant')).toHaveTextContent('Global Enterprise Holdings');
      expect(screen.getByTestId('company')).toHaveTextContent('US Technology Inc');
    });
  });
});
