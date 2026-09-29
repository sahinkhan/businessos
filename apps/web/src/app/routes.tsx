import React, { Suspense, useEffect, useState, useSyncExternalStore } from 'react';
import { Routes, Route } from 'react-router-dom';
import './coreRoutes';
import { AppShell } from '../shell/AppShell';
import { ProtectedRoute } from '../auth/ProtectedRoute';
import { LoginPage } from '../auth/LoginPage';
import { ForbiddenPage } from '../pages/states/ForbiddenPage';
import { NotFoundPage } from '../pages/states/NotFoundPage';
import { Spinner } from '../components/feedback/Spinner';
import { ErrorBoundary } from '../telemetry/ErrorBoundary';
import { routeRegistry, RouteContribution } from '../navigation/routeRegistry';
import { usePermission } from '../permissions/PermissionContext';
import { useScope } from '../scope/ScopeContext';

const DemoLoginPage =
  import.meta.env.DEV && import.meta.env.VITE_BOS_DEMO_LOGIN === '1'
    ? React.lazy(() =>
        import('../auth/DemoLoginPage').then((module) => ({ default: module.DemoLoginPage }))
      )
    : null;

const lazyPages = new WeakMap<RouteContribution, React.LazyExoticComponent<React.ComponentType>>();
function page(route: RouteContribution) {
  let component = lazyPages.get(route);
  if (!component) {
    component = React.lazy(route.loader);
    lazyPages.set(route, component);
  }
  return component;
}

const RouteGate: React.FC<{ route: RouteContribution }> = ({ route }) => {
  const { scope, isLoading } = useScope();
  const { canPerformAction, loadAction } = usePermission();
  const [checked, setChecked] = useState(!route.permission);
  useEffect(() => {
    let active = true;
    setChecked(!route.permission);
    if (route.permission)
      void loadAction(route.permission.action, route.permission.resource).then(() => {
        if (active) setChecked(true);
      });
    return () => {
      active = false;
    };
  }, [route, loadAction, scope.companyId]);
  if (!route.enabled) return <NotFoundPage />;
  if (isLoading) return <Spinner size="lg" />;
  if (!scope.companyId) return <ForbiddenPage />;
  if (!checked) return <Spinner size="lg" />;
  if (route.permission && !canPerformAction(route.permission.action, route.permission.resource))
    return <ForbiddenPage />;
  const Page = page(route);
  return (
    <ErrorBoundary>
      <Suspense fallback={<Spinner size="lg" />}>
        <Page />
      </Suspense>
    </ErrorBoundary>
  );
};

export const AppRoutes: React.FC = () => {
  const routes = useSyncExternalStore(routeRegistry.subscribe, routeRegistry.getAll);
  return (
    <Routes>
      <Route
        path="/login"
        element={
          DemoLoginPage ? (
            <Suspense fallback={<Spinner size="lg" />}>
              <DemoLoginPage />
            </Suspense>
          ) : (
            <LoginPage />
          )
        }
      />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        {routes
          .filter((route) => route.enabled)
          .map((route) =>
            route.path === '/' ? (
              <Route key={route.id} index element={<RouteGate route={route} />} />
            ) : (
              <Route
                key={route.id}
                path={route.path.slice(1)}
                element={<RouteGate route={route} />}
              />
            )
          )}
        <Route path="forbidden" element={<ForbiddenPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
};
