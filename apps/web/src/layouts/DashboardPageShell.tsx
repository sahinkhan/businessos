import React from 'react';

export interface DashboardPageShellProps {
  title?: string;
  children: React.ReactNode;
}

export const DashboardPageShell: React.FC<DashboardPageShellProps> = ({ title, children }) => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {title && (
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          {title}
        </h1>
      )}
      {children}
    </div>
  );
};
