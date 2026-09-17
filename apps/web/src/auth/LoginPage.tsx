import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from './AuthContext';
import { TextInput } from '../components/inputs/TextInput';
import { Button } from '../components/actions/Button';
import { FormField } from '../components/form/FormField';
import { Alert } from '../components/feedback/Alert';

function safeReturnPath(state: unknown): string {
  if (typeof state !== 'object' || state === null) return '/';
  const from = (state as { from?: { pathname?: unknown } }).from?.pathname;
  return typeof from === 'string' &&
    from.startsWith('/') &&
    !from.startsWith('//') &&
    !from.includes('\\')
    ? from
    : '/';
}

export const LoginPage: React.FC = () => {
  const { login, isLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const returnPath = safeReturnPath(location.state);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!email) {
      setError('Please enter your work email.');
      return;
    }
    try {
      await login(email, password);
      navigate(returnPath, { replace: true });
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : 'Login failed.');
    }
  };

  return (
    <main
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        backgroundColor: 'var(--color-surface-canvas)',
        padding: '16px',
      }}
    >
      <section
        aria-labelledby="login-title"
        style={{
          width: '100%',
          maxWidth: '400px',
          backgroundColor: 'var(--color-surface-card)',
          borderRadius: '10px',
          border: '1px solid var(--color-border-subtle)',
          boxShadow: 'var(--shadow-modal)',
          padding: '32px',
        }}
      >
        <h1 id="login-title">BusinessOS</h1>
        {error && (
          <Alert severity="danger" onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}
        <form onSubmit={handleSubmit}>
          <FormField label="Work email" required>
            <TextInput
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="username"
              required
            />
          </FormField>
          <FormField label="Password" required>
            <TextInput
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </FormField>
          <Button type="submit" variant="primary" size="lg" isLoading={isLoading}>
            Sign in
          </Button>
        </form>
      </section>
    </main>
  );
};
