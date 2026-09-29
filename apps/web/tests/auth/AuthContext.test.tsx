import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { AuthProvider, useAuth } from '../../src/auth/AuthContext';
import type { AuthAdapter } from '../../src/auth/authAdapter';
import type { SessionInfo } from '../../src/auth/types';
import { securityContext } from '../../src/api/securityContext';

const session: SessionInfo = {
  id: 'server-session',
  tenantId: 'tenant-a',
  companyId: 'company-x',
  siteId: 'site-x',
  csrfToken: 'server-csrf',
  expiresAt: Date.now() / 1000 + 3600,
  user: { id: 'user-a', name: 'User A', tenantId: 'tenant-a' },
};

const Probe = () => {
  const auth = useAuth();
  return (
    <>
      <div data-testid="status">{auth.status}</div>
      <button onClick={() => void auth.logout()}>Logout</button>
    </>
  );
};

describe('authoritative browser session', () => {
  it('is unknown and closed until the backend session resolves', async () => {
    let finish!: (value: SessionInfo | null) => void;
    const adapter: AuthAdapter = {
      getSession: () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
      startLogin: async () => 'https://idp.example/authorize',
      logout: async () => {},
    };
    render(
      <AuthProvider adapter={adapter}>
        <Probe />
      </AuthProvider>
    );
    expect(screen.getByTestId('status')).toHaveTextContent('initializing');
    expect(securityContext.current()).toBeNull();
    finish(null);
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'));
  });

  it('uses the server session and clears authority before logout completes', async () => {
    const finishLogout = vi.fn();
    const adapter: AuthAdapter = {
      getSession: async () => session,
      startLogin: async () => 'https://idp.example/authorize',
      logout: async () => {
        finishLogout();
      },
    };
    render(
      <AuthProvider adapter={adapter}>
        <Probe />
      </AuthProvider>
    );
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
    expect(localStorage.getItem('businessos.auth.session')).toBeNull();
    fireEvent.click(screen.getByText('Logout'));
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'));
    expect(securityContext.current()).toBeNull();
    expect(finishLogout).toHaveBeenCalledOnce();
  });

  it('fails closed when recovery fails', async () => {
    const adapter: AuthAdapter = {
      getSession: async () => {
        throw new Error('network failure');
      },
      startLogin: async () => 'https://idp.example/authorize',
      logout: async () => {},
    };
    render(
      <AuthProvider adapter={adapter}>
        <Probe />
      </AuthProvider>
    );
    await waitFor(() =>
      expect(screen.getByTestId('status')).toHaveTextContent('service_unavailable')
    );
    expect(securityContext.current()).toBeNull();
  });
});
