import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from '../../src/auth/AuthContext';
import { ScopeProvider } from '../../src/scope/ScopeContext';
import { MockScopeAdapter } from '../../src/scope/mockScopeAdapter';
import { PermissionProvider } from '../../src/permissions/PermissionContext';
import { PermissionBoundary } from '../../src/permissions/PermissionBoundary';
import { FieldPolicyWrapper } from '../../src/permissions/FieldPolicyWrapper';
import { HttpPolicyAdapter, MockPolicyAdapter } from '../../src/permissions/policyAdapter';
import { PolicySecurityContext } from '../../src/permissions/types';
import { TEST_SESSION, TEST_TENANTS, TEST_USER } from '../fixtures/security';

const wrapper = (adapter: MockPolicyAdapter, child: React.ReactNode) => (
  <AuthProvider initialUser={TEST_USER} initialSession={TEST_SESSION}>
    <ScopeProvider adapter={new MockScopeAdapter(TEST_TENANTS)}>
      <PermissionProvider adapter={adapter}>{child}</PermissionProvider>
    </ScopeProvider>
  </AuthProvider>
);

describe('Phase 4 policy presentation', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('denies while an action decision is pending, then renders only a trusted grant', async () => {
    render(
      wrapper(
        new MockPolicyAdapter({
          'ledger:read': { allowed: true, reason: 'Trusted test decision' },
        }),
        <PermissionBoundary action="read" resource="ledger" fallback={<span>Denied</span>}>
          <span>Ledger</span>
        </PermissionBoundary>
      )
    );

    expect(screen.getByText('Denied')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Ledger')).toBeInTheDocument());
  });

  it('keeps unknown field access hidden while pending and after a missing decision', async () => {
    const adapter = new MockPolicyAdapter();
    render(
      wrapper(
        adapter,
        <FieldPolicyWrapper resource="employee" field="secret">
          <span data-testid="secret">classified</span>
        </FieldPolicyWrapper>
      )
    );

    expect(screen.queryByTestId('secret')).not.toBeInTheDocument();
    await waitFor(() =>
      expect(
        adapter.getCachedFieldAccess('employee', 'secret', {
          principalId: TEST_USER.id,
          tenantId: 'tenant_one',
          legalEntityId: 'company_one',
          companyId: 'company_one',
          siteId: 'site_one',
        })
      ).not.toBeNull()
    );
    expect(screen.queryByTestId('secret')).not.toBeInTheDocument();
  });

  it('renders a field only after a trusted readable decision arrives', async () => {
    render(
      wrapper(
        new MockPolicyAdapter(
          {},
          {
            'employee.name': {
              fieldName: 'name',
              readable: true,
              writable: true,
              masked: false,
            },
          }
        ),
        <FieldPolicyWrapper resource="employee" field="name">
          <span data-testid="name">Visible</span>
        </FieldPolicyWrapper>
      )
    );

    expect(screen.queryByTestId('name')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('name')).toBeInTheDocument());
  });

  it('fails closed for unavailable and malformed production field decisions', async () => {
    const context: PolicySecurityContext = {
      principalId: 'p1',
      tenantId: 't1',
      companyId: 'c1',
      siteId: 's1',
    };
    global.fetch = vi.fn().mockRejectedValue(new Error('offline'));
    const unavailable = await new HttpPolicyAdapter().evaluateFieldAccess(
      'employee',
      'salary',
      context
    );
    expect(unavailable).toMatchObject({ readable: false, writable: false, masked: true });

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ readable: true }),
    });
    const malformed = await new HttpPolicyAdapter().evaluateFieldAccess(
      'employee',
      'salary',
      context
    );
    expect(malformed).toMatchObject({ readable: false, writable: false, masked: true });
  });

  it('translates exact Phase 4 field decisions without inventing write access', async () => {
    const context: PolicySecurityContext = {
      principalId: 'p1',
      tenantId: 't1',
      companyId: 'c1',
      siteId: 's1',
    };
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          allowed: true,
          access_type: 'mask',
          mask_pattern: '***-**-####',
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ allowed: false, access_type: 'deny', mask_pattern: null }),
      });

    await expect(
      new HttpPolicyAdapter().evaluateFieldAccess('employee', 'ssn', context)
    ).resolves.toMatchObject({
      readable: true,
      writable: false,
      masked: true,
      maskPattern: '***-**-####',
    });
  });

  it('isolates cached decisions across principals and organization scopes', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ allowed: true, reason: 'trusted' }),
    });
    const adapter = new HttpPolicyAdapter();
    const first = {
      principalId: 'p1',
      tenantId: 't1',
      companyId: 'c1',
      siteId: 's1',
    };
    const second = { ...first, principalId: 'p2' };
    await adapter.evaluateAuthorization({ ...first, action: 'read', resourceType: 'ledger' });
    expect(adapter.getCachedAuthorization('read', 'ledger', first)?.allowed).toBe(true);
    expect(adapter.getCachedAuthorization('read', 'ledger', second)).toBeNull();
  });
});
