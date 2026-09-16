import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { Breadcrumbs } from './Breadcrumbs';
import { CommandPalette } from '../command-palette/CommandPalette';
import { NotificationDrawer } from '../notifications/NotificationDrawer';
import { SessionExpiryModal } from '../auth/SessionExpiryModal';

export const AppShell: React.FC = () => {
  const [isNotificationsOpen, setNotificationsOpen] = useState(false);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Accessible skip link */}
      <a
        href="#main-content"
        style={{
          position: 'absolute',
          top: '-100px',
          left: '16px',
          backgroundColor: 'var(--color-action-primary)',
          color: 'white',
          padding: '8px 16px',
          borderRadius: '4px',
          zIndex: 9999,
          fontWeight: 600,
        }}
        onFocus={(e) => {
          e.currentTarget.style.top = '16px';
        }}
        onBlur={(e) => {
          e.currentTarget.style.top = '-100px';
        }}
      >
        Skip to main content
      </a>

      {/* Global Header */}
      <Header onOpenNotifications={() => setNotificationsOpen(true)} />

      {/* Body: Sidebar + Main Content */}
      <div style={{ display: 'flex', flex: 1 }}>
        <Sidebar />
        <main
          id="main-content"
          tabIndex={-1}
          style={{
            flex: 1,
            padding: '24px 32px',
            backgroundColor: 'var(--color-surface-canvas)',
            outline: 'none',
            overflowX: 'hidden',
          }}
        >
          <Breadcrumbs />
          <Outlet />
        </main>
      </div>

      {/* Overlays */}
      <CommandPalette />
      <NotificationDrawer
        isOpen={isNotificationsOpen}
        onClose={() => setNotificationsOpen(false)}
      />
      <SessionExpiryModal />
    </div>
  );
};
