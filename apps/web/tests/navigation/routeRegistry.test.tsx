import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from '../../src/auth/AuthContext';
import { AppRoutes } from '../../src/app/routes';
import { routeRegistry, RouteRegistry } from '../../src/navigation/routeRegistry';
import { ScopeProvider } from '../../src/scope/ScopeContext';
import { MockScopeAdapter } from '../../src/scope/mockScopeAdapter';
import { PermissionProvider } from '../../src/permissions/PermissionContext';
import { MockPolicyAdapter } from '../../src/permissions/policyAdapter';
import { NavigationProvider } from '../../src/navigation/NavigationContext';
import { ThemeProvider } from '../../src/design-system/theme/ThemeContext';
import { I18nProvider } from '../../src/i18n/I18nContext';
import { NotificationProvider } from '../../src/notifications/NotificationContext';
import { ToastProvider } from '../../src/components/feedback/Toast';
import { TEST_SESSION, TEST_TENANTS, TEST_USER } from '../fixtures/security';

const contribution = (
  id: string,
  path: string,
  loader = async () => ({ default: () => <div /> })
) => ({
  id,
  path,
  moduleOwner: 'test.module',
  component: loader,
});

describe('lazy module route registry', () => {
  afterEach(() => {
    cleanup();
    routeRegistry.unregister('future_module');
  });

  it('rejects duplicate IDs and paths and supports unregister', () => {
    const registry = new RouteRegistry();
    registry.register(contribution('one', 'one'));
    expect(() => registry.register(contribution('one', 'two'))).toThrow(/route ID/);
    expect(() => registry.register(contribution('two', '/one/'))).toThrow(/path/);
    expect(() => registry.register(contribution('unsafe', '/\\external.example'))).toThrow(
      /unsafe path/
    );
    expect(registry.unregister('one')).toBe(true);
    expect(registry.has('one')).toBe(false);
  });

  it('orders contributions deterministically', () => {
    const registry = new RouteRegistry();
    registry.register({ ...contribution('z', 'z'), order: 10 });
    registry.register({ ...contribution('a', 'a'), order: 10 });
    expect(registry.getAll().map((route) => route.id)).toEqual(['a', 'z']);
  });

  it('does not execute the lazy loader until the contributed route renders', async () => {
    const loader = vi.fn(async () => ({
      default: () => <div data-testid="future-page">Future module</div>,
    }));
    routeRegistry.register(contribution('future_module', 'future/module', loader));
    expect(loader).not.toHaveBeenCalled();

    render(
      <MemoryRouter initialEntries={['/future/module']}>
        <ThemeProvider>
          <I18nProvider>
            <AuthProvider initialUser={TEST_USER} initialSession={TEST_SESSION}>
              <ScopeProvider adapter={new MockScopeAdapter(TEST_TENANTS)}>
                <PermissionProvider adapter={new MockPolicyAdapter()}>
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

    await waitFor(() => expect(screen.getByTestId('future-page')).toBeInTheDocument());
    expect(loader).toHaveBeenCalledTimes(1);
  });
});
