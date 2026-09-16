import React from 'react';
import { Routes, Route } from 'react-router-dom';
import { AppShell } from '../shell/AppShell';
import { ProtectedRoute } from '../auth/ProtectedRoute';
import { LoginPage } from '../auth/LoginPage';
import { DashboardOverview } from '../pages/DashboardOverview';
import { ComponentShowcase } from '../pages/ComponentShowcase';
import { DataTableDemoPage } from '../pages/DataTableDemoPage';
import { FormsDemoPage } from '../pages/FormsDemoPage';
import { LayoutsDemoPage } from '../pages/LayoutsDemoPage';
import { SettingsPage } from '../pages/SettingsPage';
import { ForbiddenPage } from '../pages/states/ForbiddenPage';
import { NotFoundPage } from '../pages/states/NotFoundPage';

export const AppRoutes: React.FC = () => {
  return (
    <Routes>
      {/* Public Routes */}
      <Route path="/login" element={<LoginPage />} />

      {/* Protected Routes inside App Shell */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<DashboardOverview />} />
        <Route path="showcase" element={<ComponentShowcase />} />
        <Route path="demo/datatable" element={<DataTableDemoPage />} />
        <Route path="demo/forms" element={<FormsDemoPage />} />
        <Route path="demo/layouts" element={<LayoutsDemoPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="forbidden" element={<ForbiddenPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
};
