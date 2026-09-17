import React, { Suspense, lazy, useMemo, useSyncExternalStore } from 'react';
import { Route, Routes } from 'react-router-dom';
import './coreRouteContributions';
import { AppShell } from '../shell/AppShell';
import { ProtectedRoute } from '../auth/ProtectedRoute';
import { LoginPage } from '../auth/LoginPage';
import { NotFoundPage } from '../pages/states/NotFoundPage';
import { ForbiddenPage } from '../pages/states/ForbiddenPage';
import { routeRegistry, ModuleRoute } from '../navigation/routeRegistry';
import { PermissionBoundary } from '../permissions/PermissionBoundary';
import { ErrorBoundary } from '../telemetry/ErrorBoundary';
import { useScope } from '../scope/ScopeContext';

const RouteLoadingFallback: React.FC = () => (
  <div role="status" aria-live="polite" style={{ padding: '24px' }}>
    Loading module…
  </div>
);

const ScopeBoundary: React.FC<{ route: ModuleRoute; children: React.ReactNode }> = ({
  route,
  children,
}) => {
  const { scope, status } = useScope();
  if (!route.requiredScope) return <>{children}</>;
  if (status !== 'ready' || !scope) return <ForbiddenPage />;
  if (route.requiredScope === 'company' && !scope.companyId) return <ForbiddenPage />;
  if (route.requiredScope === 'site' && !scope.siteId) return <ForbiddenPage />;
  return <>{children}</>;
};

const RouteRenderer: React.FC<{ route: ModuleRoute }> = ({ route }) => {
  const LazyComponent = useMemo(() => lazy(route.component), [route.component]);
  const ModuleBoundary = route.errorBoundary ?? ErrorBoundary;

  let content: React.ReactNode = (
    <ModuleBoundary>
      <Suspense fallback={<RouteLoadingFallback />}>
        <LazyComponent />
      </Suspense>
    </ModuleBoundary>
  );

  content = <ScopeBoundary route={route}>{content}</ScopeBoundary>;

  if (route.requiredPermission) {
    content = (
      <PermissionBoundary
        action={route.requiredPermission.action}
        resource={route.requiredPermission.resource}
        fallback={<ForbiddenPage />}
      >
        {content}
      </PermissionBoundary>
    );
  }

  return <>{content}</>;
};

export const AppRoutes: React.FC = () => {
  const registeredRoutes = useSyncExternalStore(
    routeRegistry.subscribe,
    routeRegistry.getSnapshot,
    routeRegistry.getSnapshot
  );

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        {registeredRoutes.map((route) =>
          route.index ? (
            <Route key={route.id} index element={<RouteRenderer route={route} />} />
          ) : (
            <Route key={route.id} path={route.path} element={<RouteRenderer route={route} />} />
          )
        )}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
};
