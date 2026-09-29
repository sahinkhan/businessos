import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import { AuthProvider } from '../../src/auth/AuthContext';
import type { AuthAdapter } from '../../src/auth/authAdapter';
import type { SessionInfo } from '../../src/auth/types';
import { ScopeProvider } from '../../src/scope/ScopeContext';
import { PermissionProvider } from '../../src/permissions/PermissionContext';
import { PermissionBoundary } from '../../src/permissions/PermissionBoundary';
import { apiClient } from '../../src/api/client';
import { securityContext } from '../../src/api/securityContext';

const session: SessionInfo = {
  id: 'session-a',
  tenantId: 'tenant-a',
  companyId: 'company-x',
  siteId: null,
  csrfToken: 'csrf',
  expiresAt: Date.now() / 1000 + 3600,
  user: { id: 'user-a', name: 'User A', tenantId: 'tenant-a' },
};
const adapter: AuthAdapter = {
  getSession: async () => session,
  startLogin: async () => 'https://idp.example',
  logout: async () => {},
};
const scopeResponse = {
  tenants: [
    {
      id: 'tenant-a',
      name: 'A',
      groups: [
        {
          id: 'group-a',
          name: 'A',
          companies: [{ id: 'company-x', name: 'X', code: 'X', currency: 'USD', sites: [] }],
        },
      ],
    },
  ],
  active_scope: {
    tenantId: 'tenant-a',
    tenantName: 'A',
    groupId: 'group-a',
    groupName: 'A',
    companyId: 'company-x',
    companyName: 'X',
    siteId: '',
    siteName: '',
  },
};
const mount = () =>
  render(
    <AuthProvider adapter={adapter}>
      <ScopeProvider>
        <PermissionProvider>
          <PermissionBoundary action="delete" resource="ledger">
            <span>Authorized Delete</span>
          </PermissionBoundary>
        </PermissionProvider>
      </ScopeProvider>
    </AuthProvider>
  );

afterEach(() => {
  vi.restoreAllMocks();
  act(() => securityContext.transition(null));
});

describe('permission presentation', () => {
  it('hides an action while pending, then shows it only on an explicit backend allow', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue(scopeResponse);
    let finish!: () => void;
    vi.spyOn(apiClient, 'post').mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = () => resolve({ allowed: true });
        })
    );
    mount();
    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(screen.queryByText('Authorized Delete')).toBeNull();
    await act(async () => {
      finish();
    });
    await waitFor(() => expect(screen.getByText('Authorized Delete')).toBeInTheDocument());
  });

  it('keeps the action hidden on policy errors', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue(scopeResponse);
    vi.spyOn(apiClient, 'post').mockRejectedValue(new Error('policy unavailable'));
    mount();
    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(screen.queryByText('Authorized Delete')).toBeNull();
  });
});
