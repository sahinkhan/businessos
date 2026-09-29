import React, { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useAuth } from './AuthContext';
import { Button } from '../components/actions/Button';
import { Alert } from '../components/feedback/Alert';
import { useI18n } from '../i18n/I18nContext';

export const LoginPage: React.FC = () => {
  const { login, isLoading } = useAuth();
  const { t } = useI18n();
  const location = useLocation();
  const from = (location.state as any)?.from?.pathname || '/';

  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await login(from);
    } catch {
      setError(t('auth.login_failed'));
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

        <form onSubmit={handleSubmit}>
          <Button
            type="submit"
            variant="primary"
            size="lg"
            isLoading={isLoading}
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
            {t('auth.continue_with_provider')}
          </Button>
        </form>
      </div>
    </div>
  );
};
