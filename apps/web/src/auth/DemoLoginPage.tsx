import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { apiClient } from '../api/client';
import { Button } from '../components/actions/Button';
import { Alert } from '../components/feedback/Alert';
import { FormField } from '../components/form/FormField';
import { TextInput } from '../components/inputs/TextInput';
import { useI18n } from '../i18n/I18nContext';
import { useAuth } from './AuthContext';

/** Loaded only by the explicit local Vite demo command; production routes use LoginPage. */
export const DemoLoginPage: React.FC = () => {
  const { isLoading, refreshToken } = useAuth();
  const { t } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const from = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname || '/';
  const [email, setEmail] = useState('admin@demo.businessos.test');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await apiClient.post('/dev/demo-login', { email, password });
      setPassword('');
      await refreshToken();
      navigate(from, { replace: true });
    } catch {
      setError(t('auth.demo_login_failed'));
    } finally {
      setSubmitting(false);
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
            {t('auth.platform_name')}
          </p>
        </div>
        {error && (
          <div style={{ marginBottom: '16px' }}>
            <Alert severity="danger" onDismiss={() => setError(null)}>
              {error}
            </Alert>
          </div>
        )}
        <p
          style={{
            color: 'var(--color-text-secondary)',
            fontSize: '0.8125rem',
            marginBottom: '16px',
            overflowWrap: 'anywhere',
          }}
        >
          {t('auth.demo_preview_help')}
        </p>
        <form onSubmit={handleSubmit}>
          <FormField label={t('auth.demo_email')} required>
            <TextInput
              id="demo-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="username"
              required
            />
          </FormField>
          <FormField label={t('auth.demo_password')} required>
            <TextInput
              id="demo-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </FormField>
          <Button
            type="submit"
            variant="primary"
            size="lg"
            isLoading={isLoading || submitting}
            style={{
              width: '100%',
              minWidth: 0,
              height: 'auto',
              minHeight: '42px',
              marginTop: '8px',
              whiteSpace: 'normal',
              overflowWrap: 'anywhere',
              textAlign: 'center',
            }}
          >
            {t('auth.demo_sign_in')}
          </Button>
        </form>
      </div>
    </div>
  );
};
