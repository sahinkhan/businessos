import React, { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useAuth } from './AuthContext';
import { Button } from '../components/actions/Button';
import { Alert } from '../components/feedback/Alert';
import { useI18n } from '../i18n/I18nContext';
import { ErrorState } from '../components/feedback/ErrorState';

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
  const { login, isLoading, status, error: sessionError, reloadSession } = useAuth();
  const location = useLocation();
  const returnPath = safeReturnPath(location.state);
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await login(returnPath);
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : t('auth.login.failed'));
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
        {(status === 'service_unavailable' || status === 'authorization_denied') && (
          <ErrorState
            title={t(
              status === 'authorization_denied'
                ? 'auth.session_denied.title'
                : 'auth.session_unavailable.title'
            )}
            message={t(
              status === 'authorization_denied'
                ? 'auth.session_denied.body'
                : 'auth.session_unavailable.body'
            )}
            error={sessionError}
            onRetry={() => void reloadSession()}
            style={{ padding: '24px 0' }}
          />
        )}
        {error && (
          <Alert severity="danger" onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}
        <form
          onSubmit={handleSubmit}
          hidden={status === 'service_unavailable' || status === 'authorization_denied'}
        >
          <Button type="submit" variant="primary" size="lg" isLoading={isLoading}>
            {t('auth.login.continue')}
          </Button>
        </form>
      </section>
    </main>
  );
};
