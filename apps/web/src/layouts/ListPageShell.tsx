import React from 'react';

export interface ListPageShellProps {
  title: string;
  description?: string;
  primaryAction?: React.ReactNode;
  secondaryActions?: React.ReactNode;
  toolbar?: React.ReactNode;
  children: React.ReactNode;
}

export const ListPageShell: React.FC<ListPageShellProps> = ({
  title,
  description,
  primaryAction,
  secondaryActions,
  toolbar,
  children,
}) => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', width: '100%' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: '16px',
        }}
      >
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
            {title}
          </h1>
          {description && (
            <p
              style={{
                fontSize: '0.875rem',
                color: 'var(--color-text-secondary)',
                marginTop: '4px',
              }}
            >
              {description}
            </p>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {secondaryActions}
          {primaryAction}
        </div>
      </div>
      {toolbar && <div>{toolbar}</div>}
      <div>{children}</div>
    </div>
  );
};
