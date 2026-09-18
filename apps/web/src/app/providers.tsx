import React, { useState } from 'react';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { ThemeProvider } from '../design-system/theme/ThemeContext';
import { AuthAdapter } from '../auth/authAdapter';
import { AuthProvider } from '../auth/AuthContext';
import { ScopeAdapter } from '../scope/scopeAdapter';
import { ScopeProvider } from '../scope/ScopeContext';
import { PolicyPresentationAdapter } from '../permissions/policyAdapter';
import { PermissionProvider } from '../permissions/PermissionContext';
import { I18nProvider } from '../i18n/I18nContext';
import { NotificationProvider } from '../notifications/NotificationContext';
import { NavigationProvider } from '../navigation/NavigationContext';
import { ToastProvider } from '../components/feedback/Toast';
import { ErrorBoundary } from '../telemetry/ErrorBoundary';

export interface AppProvidersProps {
  children: React.ReactNode;
  authAdapter?: AuthAdapter;
  scopeAdapter?: ScopeAdapter;
  policyAdapter?: PolicyPresentationAdapter;
}

const ApplicationRouter: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [router] = useState(() => createBrowserRouter([{ path: '*', element: <>{children}</> }]));
  return <RouterProvider router={router} />;
};

export const AppProviders: React.FC<AppProvidersProps> = ({
  children,
  authAdapter,
  scopeAdapter,
  policyAdapter,
}) => (
  <ErrorBoundary>
    <ThemeProvider>
      <I18nProvider>
        <AuthProvider adapter={authAdapter}>
          <ScopeProvider adapter={scopeAdapter}>
            <PermissionProvider adapter={policyAdapter}>
              <NotificationProvider>
                <NavigationProvider>
                  <ToastProvider>
                    <ApplicationRouter>{children}</ApplicationRouter>
                  </ToastProvider>
                </NavigationProvider>
              </NotificationProvider>
            </PermissionProvider>
          </ScopeProvider>
        </AuthProvider>
      </I18nProvider>
    </ThemeProvider>
  </ErrorBoundary>
);
