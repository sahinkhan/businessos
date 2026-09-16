import React from 'react';
import { BrowserRouter } from 'react-router-dom';
import { ThemeProvider } from '../design-system/theme/ThemeContext';
import { AuthProvider } from '../auth/AuthContext';
import { ScopeProvider } from '../scope/ScopeContext';
import { PermissionProvider } from '../permissions/PermissionContext';
import { I18nProvider } from '../i18n/I18nContext';
import { NotificationProvider } from '../notifications/NotificationContext';
import { NavigationProvider } from '../navigation/NavigationContext';
import { ToastProvider } from '../components/feedback/Toast';
import { ErrorBoundary } from '../telemetry/ErrorBoundary';

export const AppProviders: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <I18nProvider>
          <AuthProvider>
            <ScopeProvider>
              <PermissionProvider>
                <NotificationProvider>
                  <NavigationProvider>
                    <ToastProvider>
                      <BrowserRouter>{children}</BrowserRouter>
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
};
