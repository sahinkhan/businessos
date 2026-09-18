import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '../../src/api/queryCache';
import { AuthProvider, useAuth } from '../../src/auth/AuthContext';
import { AuthAdapter, HttpAuthAdapter, MockAuthAdapter } from '../../src/auth/authAdapter';
import { TEST_SESSION } from '../fixtures/security';
import { ApiError } from '../../src/api/types';
import { MemoryRouter } from 'react-router-dom';
import { LoginPage } from '../../src/auth/LoginPage';
import { I18nProvider } from '../../src/i18n/I18nContext';

const Consumer = () => {
  const { user, session, isAuthenticated, isLoading, status, error, logout, reloadSession } =
    useAuth();
  return (
    <div>
      <span data-testid="status">{isAuthenticated ? 'authenticated' : 'unauthenticated'}</span>
      <span data-testid="user">{user?.email ?? 'none'}</span>
      <span data-testid="credential-state">{session ? 'safe-session' : 'none'}</span>
      <span data-testid="loading">{String(isLoading)}</span>
      <span data-testid="auth-status">{status}</span>
      <span data-testid="auth-error">{error ?? 'none'}</span>
      <button onClick={() => void logout()}>Logout</button>
      <button onClick={() => void reloadSession()}>Reload</button>
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

  it('settles an unavailable bootstrap and can recover on an explicit reload', async () => {
    let attempt = 0;
    const adapter: AuthAdapter = {
      getSession: vi.fn(async () => {
        attempt += 1;
        if (attempt === 1) throw new TypeError('Session service unavailable');
        return TEST_SESSION;
      }),
      startLogin: vi.fn(),
      logout: vi.fn(),
    };
    render(
      <AuthProvider adapter={adapter}>
        <Consumer />
      </AuthProvider>
    );

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'));
    expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated');
    expect(screen.getByTestId('auth-status')).toHaveTextContent('service_unavailable');
    fireEvent.click(screen.getByText('Reload'));
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
    expect(adapter.getSession).toHaveBeenCalledTimes(2);
  });

  it.each([
    ['500 response', new ApiError(500, { code: 'unavailable', message: 'Session unavailable' })],
    ['network failure', new TypeError('Failed to fetch')],
    ['timeout', new DOMException('Timed out', 'TimeoutError')],
    ['malformed response', new Error('Malformed current-session response')],
  ])('exposes a recoverable state for %s', async (_label, failure) => {
    const adapter: AuthAdapter = {
      getSession: vi.fn().mockRejectedValue(failure),
      startLogin: vi.fn(),
      logout: vi.fn(),
    };
    render(
      <AuthProvider adapter={adapter}>
        <Consumer />
      </AuthProvider>
    );
    await waitFor(() =>
      expect(screen.getByTestId('auth-status')).toHaveTextContent('service_unavailable')
    );
    expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated');
    expect(screen.getByTestId('auth-error')).not.toHaveTextContent('none');
  });

  it('recovers from a service failure to a trusted unauthenticated response', async () => {
    const adapter: AuthAdapter = {
      getSession: vi
        .fn()
        .mockRejectedValueOnce(new TypeError('Failed to fetch'))
        .mockResolvedValueOnce(null),
      startLogin: vi.fn(),
      logout: vi.fn(),
    };
    render(
      <AuthProvider adapter={adapter}>
        <Consumer />
      </AuthProvider>
    );
    await waitFor(() =>
      expect(screen.getByTestId('auth-status')).toHaveTextContent('service_unavailable')
    );
    fireEvent.click(screen.getByText('Reload'));
    await waitFor(() =>
      expect(screen.getByTestId('auth-status')).toHaveTextContent('unauthenticated')
    );
    expect(adapter.getSession).toHaveBeenCalledTimes(2);
  });

  it('presents a production retry control and recovers when the service returns', async () => {
    const adapter: AuthAdapter = {
      getSession: vi
        .fn()
        .mockRejectedValueOnce(new TypeError('Failed to fetch'))
        .mockResolvedValueOnce(TEST_SESSION),
      startLogin: vi.fn(),
      logout: vi.fn(),
    };
    render(
      <MemoryRouter>
        <I18nProvider>
          <AuthProvider adapter={adapter}>
            <LoginPage />
          </AuthProvider>
        </I18nProvider>
      </MemoryRouter>
    );
    const retry = await screen.findByRole('button', { name: 'Retry' });
    expect(screen.getByText('Session service unavailable')).toBeInTheDocument();
    fireEvent.click(retry);
    await waitFor(() => expect(screen.queryByText('Session service unavailable')).toBeNull());
    expect(adapter.getSession).toHaveBeenCalledTimes(2);
  });
});
