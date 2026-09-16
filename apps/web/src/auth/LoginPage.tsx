import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from './AuthContext';
import { TextInput } from '../components/inputs/TextInput';
import { Button } from '../components/actions/Button';
import { FormField } from '../components/form/FormField';
import { Alert } from '../components/feedback/Alert';

export const LoginPage: React.FC = () => {
  const { login, isLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as any)?.from?.pathname || '/';

  const [email, setEmail] = useState('admin@businessos.internal');
  const [password, setPassword] = useState('password');
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) {
      setError('Please enter your work email.');
      return;
    }
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err: any) {
      setError(err.message || 'Login failed. Please verify credentials.');
    }
  };

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        backgroundColor: 'var(--color-surface-canvas)',
        padding: '16px',
      }}
    >
      <div
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
        <div style={{ textAlign: 'center', marginBottom: '24px' }}>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
            BusinessOS
          </h1>
          <p
            style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)', marginTop: '4px' }}
          >
            Enterprise Management Platform
          </p>
        </div>

        {error && (
          <div style={{ marginBottom: '16px' }}>
            <Alert severity="danger" onDismiss={() => setError(null)}>
              {error}
            </Alert>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <FormField label="Work email" required>
            <TextInput
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@enterprise.com"
              autoComplete="username"
              required
            />
          </FormField>

          <FormField label="Password" required>
            <TextInput
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              required
            />
          </FormField>

          <Button
            type="submit"
            variant="primary"
            size="lg"
            isLoading={isLoading}
            style={{ width: '100%', marginTop: '8px' }}
          >
            Sign in
          </Button>
        </form>
      </div>
    </div>
  );
};
