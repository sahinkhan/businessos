import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AuthProvider } from '../../src/auth/AuthContext';
import type { AuthAdapter } from '../../src/auth/authAdapter';
import type { SessionInfo } from '../../src/auth/types';
import { apiClient } from '../../src/api/client';
import { securityContext } from '../../src/api/securityContext';
import { ScopeProvider, useScope } from '../../src/scope/ScopeContext';

const session: SessionInfo = {
  id: 'session-x',
  tenantId: 'tenant-a',
  companyId: 'company-x',
  siteId: null,
  csrfToken: 'csrf-x',
  expiresAt: Date.now() / 1000 + 3600,
  user: { id: 'user-a', name: 'User A', tenantId: 'tenant-a' },
};
const option = (id: string) => ({ id, name: id });
const hierarchy = {
  tenants: [
    {
      id: 'tenant-a',
      name: 'Tenant A',
      groups: [
        {
          id: 'group-a',
          name: 'Group A',
          companies: [
            { ...option('company-x'), code: 'X', currency: 'USD', sites: [] },
            { ...option('company-y'), code: 'Y', currency: 'USD', sites: [] },
          ],
        },
      ],
    },
  ],
  active_scope: {
    tenantId: 'tenant-a',
    tenantName: 'Tenant A',
    groupId: 'group-a',
    groupName: 'Group A',
    companyId: 'company-x',
    companyName: 'company-x',
    siteId: '',
    siteName: '',
  },
};
const adapter: AuthAdapter = {
  getSession: async () => session,
  startLogin: async () => 'https://idp.example/authorize',
  logout: async () => {},
};
const Probe = () => {
  const { scope, tenants, setCompany } = useScope();
  return (
    <>
      <div data-testid="company">{scope.companyId}</div>
      <div data-testid="options">{tenants.length}</div>
      <button onClick={() => setCompany('company-y')}>Switch</button>
    </>
  );
};

afterEach(() => {
  vi.restoreAllMocks();
  act(() => securityContext.transition(null));
});

describe('authoritative scope presentation', () => {
  it('loads only backend options and clears the old company before selection completes', async () => {
    let finish!: () => void;
    vi.spyOn(apiClient, 'get').mockResolvedValue(hierarchy);
    vi.spyOn(apiClient, 'post').mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = () => resolve({});
        })
    );
    render(
      <AuthProvider adapter={adapter}>
        <ScopeProvider>
          <Probe />
        </ScopeProvider>
      </AuthProvider>
    );
    await waitFor(() => expect(screen.getByTestId('company')).toHaveTextContent('company-x'));
    expect(screen.getByTestId('options')).toHaveTextContent('1');
    fireEvent.click(screen.getByText('Switch'));
    expect(screen.getByTestId('company')).toBeEmptyDOMElement();
    expect(securityContext.current()?.companyId).toBeNull();
    await act(async () => {
      finish();
    });
  });

  it('rejects a scope response that disagrees with the backend session', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      ...hierarchy,
      active_scope: { ...hierarchy.active_scope, companyId: 'company-y' },
    });
    render(
      <AuthProvider adapter={adapter}>
        <ScopeProvider>
          <Probe />
        </ScopeProvider>
      </AuthProvider>
    );
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId('options')).toHaveTextContent('0'));
    expect(screen.getByTestId('company')).toBeEmptyDOMElement();
  });
});
