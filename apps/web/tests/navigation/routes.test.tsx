import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Outlet } from 'react-router-dom';
import { routeRegistry } from '../../src/navigation/routeRegistry';
import { AppRoutes } from '../../src/app/routes';

const policy = vi.hoisted(() => ({ allowed: false, loadAction: async () => undefined }));

vi.mock('../../src/auth/ProtectedRoute', () => ({
  ProtectedRoute: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('../../src/shell/AppShell', () => ({ AppShell: () => <Outlet /> }));
vi.mock('../../src/scope/ScopeContext', () => ({
  useScope: () => ({ scope: { companyId: 'company-1' }, isLoading: false }),
}));
vi.mock('../../src/permissions/PermissionContext', () => ({
  usePermission: () => ({
    canPerformAction: () => policy.allowed,
    loadAction: policy.loadAction,
  }),
}));

const route = (id: string, label: string) => ({
  id,
  path: '/test-module',
  owner: 'test.module',
  enabled: true,
  loader: async () => ({ default: () => <div>{label}</div> }),
});

afterEach(() => {
  act(() => routeRegistry.unregister('test.module'));
  policy.allowed = false;
});

describe('module route rendering', () => {
  it('loads a newly registered page after a route ID is reused', async () => {
    routeRegistry.register(route('test.module', 'First page'));
    const view = render(
      <MemoryRouter initialEntries={['/test-module']}>
        <AppRoutes />
      </MemoryRouter>
    );
    expect(await screen.findByText('First page')).toBeInTheDocument();
    act(() => {
      routeRegistry.unregister('test.module');
      routeRegistry.register(route('test.module', 'Replacement page'));
    });
    view.rerender(
      <MemoryRouter initialEntries={['/test-module']}>
        <AppRoutes />
      </MemoryRouter>
    );
    expect(await screen.findByText('Replacement page')).toBeInTheDocument();
  });

  it('hides disabled routes and denies pending or denied route decisions', async () => {
    routeRegistry.register({
      ...route('test.module', 'Protected page'),
      enabled: false,
      permission: { action: 'read', resource: 'test.module' },
    });
    const view = render(
      <MemoryRouter initialEntries={['/test-module']}>
        <AppRoutes />
      </MemoryRouter>
    );
    expect(await screen.findByRole('heading', { name: /not found/i })).toBeInTheDocument();
    act(() => routeRegistry.setEnabled('test.module', true));
    view.rerender(
      <MemoryRouter initialEntries={['/test-module']}>
        <AppRoutes />
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /authorization denied/i })).toBeInTheDocument()
    );
    expect(screen.queryByText('Protected page')).not.toBeInTheDocument();
  });
});
