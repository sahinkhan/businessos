import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthProvider } from '../../src/auth/AuthContext';
import type { AuthAdapter } from '../../src/auth/authAdapter';
import type { SessionInfo } from '../../src/auth/types';
import { apiClient } from '../../src/api/client';
import { securityContext } from '../../src/api/securityContext';
import { ScopeProvider, useScope } from '../../src/scope/ScopeContext';
import { ScopeSwitcher } from '../../src/scope/ScopeSwitcher';
import { I18nProvider } from '../../src/i18n/I18nContext';

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
  it('restores keyboard focus only after the backend accepts and reloads a company scope', async () => {
    const user = userEvent.setup();
    let currentSession = session;
    let completePost!: () => void;
    const scopeHierarchy = {
      ...hierarchy,
      tenants: [
        {
          ...hierarchy.tenants[0],
          groups: [
            {
              ...hierarchy.tenants[0].groups[0],
              companies: [
                hierarchy.tenants[0].groups[0].companies[0],
                {
                  ...hierarchy.tenants[0].groups[0].companies[1],
                  sites: [{ id: 'site-y', name: 'Site Y', code: 'SY' }],
                },
              ],
            },
          ],
        },
      ],
    };
    vi.spyOn(apiClient, 'get').mockImplementation(async () => ({
      ...scopeHierarchy,
      active_scope:
        currentSession.companyId === 'company-y'
          ? {
              ...hierarchy.active_scope,
              companyId: 'company-y',
              companyName: 'company-y',
              siteId: 'site-y',
              siteName: 'Site Y',
            }
          : hierarchy.active_scope,
    }));
    vi.spyOn(apiClient, 'post').mockImplementation(
      () =>
        new Promise((resolve) => {
          completePost = () => {
            currentSession = { ...session, companyId: 'company-y', siteId: 'site-y' };
            resolve({});
          };
        })
    );
    render(
      <AuthProvider adapter={{ ...adapter, getSession: async () => currentSession }}>
        <ScopeProvider>
          <I18nProvider>
            <ScopeSwitcher />
          </I18nProvider>
        </ScopeProvider>
      </AuthProvider>
    );
    const trigger = await screen.findByRole('button', { name: 'Switch organization scope' });
    await waitFor(() => expect(trigger).toBeEnabled());
    await user.tab();
    await user.keyboard('{Enter}');
    await user.tab();
    await user.tab();
    await user.tab();
    expect(screen.getByRole('button', { name: 'company-y (Y)' })).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(apiClient.post).toHaveBeenCalledWith('/v1/organization/active-scope', {
      tenant_id: 'tenant-a',
      enterprise_group_id: 'group-a',
      company_id: 'company-y',
      operating_site_id: 'site-y',
    });
    expect(document.activeElement).toBe(document.body);
    expect(screen.queryByRole('button', { name: '• Site Y' })).not.toBeInTheDocument();

    await act(async () => completePost());
    await waitFor(() => expect(screen.getByRole('button', { name: '• Site Y' })).toHaveFocus());
    expect(document.activeElement).not.toBe(document.body);
  });

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
