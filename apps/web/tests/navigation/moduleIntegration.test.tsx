import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { routeRegistry } from '../../src/navigation/routeRegistry';
import { navigationRegistry } from '../../src/navigation/registry';
import { AppRoutes } from '../../src/app/routes';
import { AuthProvider } from '../../src/auth/AuthContext';
import { ScopeProvider } from '../../src/scope/ScopeContext';
import { PermissionProvider } from '../../src/permissions/PermissionContext';
import { NavigationProvider } from '../../src/navigation/NavigationContext';
import { NotificationProvider } from '../../src/notifications/NotificationContext';
import { ToastProvider } from '../../src/components/feedback/Toast';
import { ThemeProvider } from '../../src/design-system/theme/ThemeContext';
import { I18nProvider } from '../../src/i18n/I18nContext';
import { UserProfile, SessionInfo } from '../../src/auth/types';

describe('Module -> RouteRegistry -> NavigationRegistry -> AppShell Conformance', () => {
  const MODULE_ROUTE_ID = 'sales_orders_list';
  const MODULE_NAV_ID = 'nav_sales_orders';
  const MODULE_PATH = 'sales/orders';

  const mockUser: UserProfile = {
    id: 'usr_sales_lead',
    email: 'lead@sales.businessos.internal',
    name: 'Sales Lead',
    tenantId: 'tenant_default',
    roles: ['sales_user'],
  };

  const mockSession: SessionInfo = {
    token: 'mock_sales_token',
    expiresAt: Math.floor(Date.now() / 1000) + 3600,
    issuedAt: Math.floor(Date.now() / 1000),
  };

  beforeEach(() => {
    // Simulate Module Route Registration
    routeRegistry.register({
      id: MODULE_ROUTE_ID,
      moduleOwner: 'sales',
      path: MODULE_PATH,
      element: <div data-testid="sales-orders-view">Sales Orders Grid Content</div>,
      title: 'Sales Orders',
      order: 25,
    });

    // Simulate Module Navigation Contribution referencing registered Route
    navigationRegistry.register({
      id: MODULE_NAV_ID,
      routeId: MODULE_ROUTE_ID,
      label: 'Sales Orders',
      path: '/' + MODULE_PATH,
      icon: 'Table',
      group: 'Sales Management',
      order: 25,
    });
  });

  afterEach(() => {
    navigationRegistry.unregister(MODULE_NAV_ID);
    routeRegistry.unregister(MODULE_ROUTE_ID);
  });

  it('proves module route and navigation integrate into AppShell dynamically without editing shell code', async () => {
    render(
      <MemoryRouter initialEntries={['/' + MODULE_PATH]}>
        <ThemeProvider>
          <I18nProvider>
            <AuthProvider initialUser={mockUser} initialSession={mockSession}>
              <ScopeProvider>
                <PermissionProvider>
                  <NotificationProvider>
                    <NavigationProvider>
                      <ToastProvider>
                        <AppRoutes />
                      </ToastProvider>
                    </NavigationProvider>
                  </NotificationProvider>
                </PermissionProvider>
              </ScopeProvider>
            </AuthProvider>
          </I18nProvider>
        </ThemeProvider>
      </MemoryRouter>
    );

    // 1. Navigation Shell receives item in Sidebar under registered group
    expect(screen.getByText('Sales Management')).toBeInTheDocument();
    const navLink = screen.getByRole('link', { name: /Sales Orders/i });
    expect(navLink).toBeInTheDocument();
    expect(navLink).toHaveAttribute('href', '/' + MODULE_PATH);

    // 2. App Shell Outlet renders Module Route component
    expect(screen.getByTestId('sales-orders-view')).toBeInTheDocument();
    expect(screen.getByText('Sales Orders Grid Content')).toBeInTheDocument();
  });
});
