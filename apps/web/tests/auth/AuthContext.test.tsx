import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '../../src/api/queryCache';
import { AuthProvider, useAuth } from '../../src/auth/AuthContext';
import { HttpAuthAdapter, MockAuthAdapter } from '../../src/auth/authAdapter';
import { TEST_SESSION, TEST_USER } from '../fixtures/security';

const Consumer = () => {
  const { user, session, isAuthenticated, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="status">{isAuthenticated ? 'authenticated' : 'unauthenticated'}</span>
      <span data-testid="user">{user?.email ?? 'none'}</span>
      <span data-testid="credential-state">{session ? 'in-memory' : 'none'}</span>
      <button onClick={() => void login(TEST_USER.email, 'secret')}>Login</button>
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

  it('starts unauthenticated and ignores persisted browser credentials', () => {
    localStorage.setItem(
      'businessos.auth.session',
      JSON.stringify({ accessToken: 'attacker-controlled', expiresAt: 9999999999 })
    );
    localStorage.setItem('businessos.auth.user', JSON.stringify(TEST_USER));

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>
    );

    expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated');
    expect(screen.getByTestId('credential-state')).toHaveTextContent('none');
  });

  it('keeps a backend-issued bearer credential in memory and never writes it to localStorage', async () => {
    const adapter = new MockAuthAdapter(TEST_USER, TEST_SESSION);
    render(
      <AuthProvider adapter={adapter}>
        <Consumer />
      </AuthProvider>
    );

    queryCache.set('prior-principal-data', { sensitive: true });
    fireEvent.click(screen.getByText('Login'));
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
    expect(screen.getByTestId('credential-state')).toHaveTextContent('in-memory');
    const storedValues = Array.from({ length: localStorage.length }, (_, index) =>
      localStorage.getItem(localStorage.key(index) ?? '')
    );
    expect(storedValues.join('')).not.toContain(TEST_SESSION.accessToken);
    expect(localStorage.getItem('businessos.auth.session')).toBeNull();
    expect(queryCache.size()).toBe(0);
  });

  it('clears principal-bound state on logout', async () => {
    queryCache.set('principal-data', { sensitive: true });
    render(
      <AuthProvider
        adapter={new MockAuthAdapter(TEST_USER, TEST_SESSION)}
        initialUser={TEST_USER}
        initialSession={TEST_SESSION}
      >
        <Consumer />
      </AuthProvider>
    );

    await act(async () => {
      fireEvent.click(screen.getByText('Logout'));
    });
    expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated');
    expect(queryCache.size()).toBe(0);
  });

  it('invalidates an expired in-memory session', async () => {
    render(
      <AuthProvider
        initialUser={TEST_USER}
        initialSession={{ ...TEST_SESSION, expiresAt: Math.floor(Date.now() / 1000) - 1 }}
      >
        <Consumer />
      </AuthProvider>
    );

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'));
    expect(screen.getByTestId('credential-state')).toHaveTextContent('none');
  });

  it('does not manufacture a production session when the backend is unavailable', async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    const adapter = new HttpAuthAdapter();
    await expect(adapter.login({ email: TEST_USER.email, password: 'secret' })).rejects.toThrow(
      'Failed to fetch'
    );
  });
});
