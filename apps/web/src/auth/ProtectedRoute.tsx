import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './AuthContext';
import { Spinner } from '../components/feedback/Spinner';
import { ErrorState } from '../components/feedback/ErrorState';
import { useI18n } from '../i18n/I18nContext';

export interface ProtectedRouteProps {
  children: React.ReactNode;
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ children }) => {
  const { isAuthenticated, isLoading, status, error, reloadSession } = useAuth();
  const location = useLocation();
  const { t } = useI18n();

  if (isLoading) {
    return (
      <div
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}
      >
        <Spinner size="lg" />
      </div>
    );
  }

  if (status === 'service_unavailable' || status === 'authorization_denied') {
    return (
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
        error={error}
        onRetry={() => void reloadSession()}
      />
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
};
