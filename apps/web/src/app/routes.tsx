import React from 'react';
import { Routes, Route } from 'react-router-dom';
import { AppShell } from '../shell/AppShell';
import { ProtectedRoute } from '../auth/ProtectedRoute';
import { LoginPage } from '../auth/LoginPage';
import { NotFoundPage } from '../pages/states/NotFoundPage';
import { ForbiddenPage } from '../pages/states/ForbiddenPage';
import { routeRegistry, ModuleRoute } from '../navigation/routeRegistry';
import { PermissionBoundary } from '../permissions/PermissionBoundary';

interface RouteWrapperProps {
  route: ModuleRoute;
}

const RouteWrapper: React.FC<RouteWrapperProps> = ({ route }) => {
  let content: React.ReactElement = route.element;

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

  if (route.errorBoundary) {
    const CustomErrorBoundary = route.errorBoundary;
    return <CustomErrorBoundary>{content}</CustomErrorBoundary>;
  }

  return content;
};

export const AppRoutes: React.FC = () => {
  const registeredRoutes = routeRegistry.getAll();

  return (
    <Routes>
      {/* Public Routes */}
      <Route path="/login" element={<LoginPage />} />

      {/* Protected Routes inside App Shell - dynamically resolved from RouteRegistry */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        {registeredRoutes.map((r) =>
          r.index ? (
            <Route key={r.id} index element={<RouteWrapper route={r} />} />
          ) : (
            <Route key={r.id} path={r.path} element={<RouteWrapper route={r} />} />
          )
        )}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
};
