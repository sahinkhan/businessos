import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import { AuthProvider, useAuth } from '../../src/auth/AuthContext';
import { MockAuthAdapter } from '../../src/auth/authAdapter';
import { UserProfile, SessionInfo } from '../../src/auth/types';

const TestAuthConsumer = () => {
  const { user, session, isAuthenticated, login, logout } = useAuth();
  return (
    <div>
      <div data-testid="auth-status">{isAuthenticated ? 'authenticated' : 'unauthenticated'}</div>
      <div data-testid="user-email">{user?.email || 'none'}</div>
      <div data-testid="token">{session?.token || 'none'}</div>
      <button onClick={() => login('operator@enterprise.com', 'secret')}>Login</button>
      <button onClick={() => logout()}>Logout</button>
    </div>
  );
};

describe('AuthContext & Session Boundary', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('starts unauthenticated when no session is stored (no auto-login as fake admin)', () => {
    render(
      <AuthProvider initialUser={null} initialSession={null}>
        <TestAuthConsumer />
      </AuthProvider>
    );

    expect(screen.getByTestId('auth-status')).toHaveTextContent('unauthenticated');
    expect(screen.getByTestId('user-email')).toHaveTextContent('none');
    expect(screen.getByTestId('token')).toHaveTextContent('none');
  });

  it('authenticates through the auth adapter and sets valid session', async () => {
    const mockUser: UserProfile = {
      id: 'usr_verified_1',
      email: 'operator@enterprise.com',
      name: 'Verified Operator',
      roles: ['operator'],
      tenantId: 'tenant_default',
      principal: {
        tenantId: 'tenant_default',
        principalId: 'usr_verified_1',
        principalType: 'user',
        authenticationStrength: 'password',
        scopes: [{ tenant_id: 'tenant_default' }],
      },
    };
    const mockSession: SessionInfo = {
      token: 'bos_token_valid',
      issuedAt: Math.floor(Date.now() / 1000),
      expiresAt: Math.floor(Date.now() / 1000) + 3600,
    };
    const adapter = new MockAuthAdapter(mockUser, mockSession);

    render(
      <AuthProvider adapter={adapter} initialUser={null} initialSession={null}>
        <TestAuthConsumer />
      </AuthProvider>
    );

    expect(screen.getByTestId('auth-status')).toHaveTextContent('unauthenticated');

    await act(async () => {
      screen.getByText('Login').click();
    });

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('authenticated');
      expect(screen.getByTestId('user-email')).toHaveTextContent('operator@enterprise.com');
      expect(screen.getByTestId('token')).toHaveTextContent('bos_token_valid');
    });

    // Logging out clears state
    await act(async () => {
      screen.getByText('Logout').click();
    });

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('unauthenticated');
      expect(screen.getByTestId('token')).toHaveTextContent('none');
    });
  });

  it('rejects stale or invalid token on mount and purges storage', async () => {
    // Inject invalid token into local storage
    localStorage.setItem(
      'businessos.auth.session',
      JSON.stringify({
        token: 'invalid_expired_token',
        issuedAt: 100,
        expiresAt: Math.floor(Date.now() / 1000) + 3600,
      })
    );
    localStorage.setItem(
      'businessos.auth.user',
      JSON.stringify({
        id: 'usr_stale',
        email: 'stale@enterprise.com',
        roles: ['user'],
        tenantId: 'tenant_default',
      })
    );

    const adapter = new MockAuthAdapter(null, null);
    // validateSession for invalid_expired_token will return null

    render(
      <AuthProvider adapter={adapter}>
        <TestAuthConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('unauthenticated');
      expect(localStorage.getItem('businessos.auth.session')).toBeNull();
    });
  });
});
