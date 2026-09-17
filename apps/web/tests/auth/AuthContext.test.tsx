import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '../../src/api/queryCache';
import { AuthProvider, useAuth } from '../../src/auth/AuthContext';
import { HttpAuthAdapter, MockAuthAdapter } from '../../src/auth/authAdapter';
import { TEST_SESSION } from '../fixtures/security';

const Consumer = () => {
  const { user, session, isAuthenticated, logout } = useAuth();
  return (
    <div>
      <span data-testid="status">{isAuthenticated ? 'authenticated' : 'unauthenticated'}</span>
      <span data-testid="user">{user?.email ?? 'none'}</span>
      <span data-testid="credential-state">{session ? 'safe-session' : 'none'}</span>
      <button onClick={() => void logout()}>Logout</button>
    </div>
  );
};

describe('backend-authoritative authentication boundary', () => {
  beforeEach(() => {
    localStorage.clear();
    queryCache.clear();
    vi.restoreAllMocks();
  });

  it('ignores persisted browser credentials and restores only the backend cookie session', async () => {
    localStorage.setItem('businessos.auth.session', JSON.stringify({ accessToken: 'attacker' }));
    render(
      <AuthProvider adapter={new MockAuthAdapter(null)}>
        <Consumer />
      </AuthProvider>
    );

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'));
    expect(screen.getByTestId('credential-state')).toHaveTextContent('none');
  });

  it('loads only a safe server projection and never writes it to browser storage', async () => {
    render(
      <AuthProvider adapter={new MockAuthAdapter(TEST_SESSION)}>
        <Consumer />
      </AuthProvider>
    );
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
    expect(screen.getByTestId('credential-state')).toHaveTextContent('safe-session');
    expect(localStorage.getItem('businessos.auth.session')).toBeNull();
  });

  it('clears principal-bound state on logout', async () => {
    queryCache.set('principal-data', { sensitive: true });
    render(
      <AuthProvider adapter={new MockAuthAdapter(TEST_SESSION)} initialSession={TEST_SESSION}>
        <Consumer />
      </AuthProvider>
    );

    await act(async () => {
      fireEvent.click(screen.getByText('Logout'));
    });
    expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated');
    expect(queryCache.size()).toBe(0);
  });

  it('invalidates an expired server projection', async () => {
    render(
      <AuthProvider
        adapter={new MockAuthAdapter(null)}
        initialSession={{ ...TEST_SESSION, expiresAt: Math.floor(Date.now() / 1000) - 1 }}
      >
        <Consumer />
      </AuthProvider>
    );
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'));
  });

  it('does not manufacture a session when the backend is unavailable', async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(new HttpAuthAdapter().getSession()).rejects.toThrow('Failed to fetch');
  });
});
