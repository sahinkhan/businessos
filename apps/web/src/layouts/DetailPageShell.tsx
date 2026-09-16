import React from 'react';
import { Card } from '../components/structure/Card';

export interface DetailPageShellProps {
  title: string;
  subtitle?: string;
  statusBadge?: React.ReactNode;
  actions?: React.ReactNode;
  tabs?: React.ReactNode;
  children: React.ReactNode;
  auditFooter?: React.ReactNode;
}

export const DetailPageShell: React.FC<DetailPageShellProps> = ({
  title,
  subtitle,
  statusBadge,
  actions,
  tabs,
  children,
  auditFooter,
}) => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', width: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
              {title}
            </h1>
            {statusBadge}
          </div>
          {subtitle && (
            <p
              style={{
                fontSize: '0.875rem',
                color: 'var(--color-text-secondary)',
                marginTop: '4px',
              }}
            >
              {subtitle}
            </p>
          )}
        </div>
        {actions && <div style={{ display: 'flex', gap: '8px' }}>{actions}</div>}
      </div>

      {tabs && <div>{tabs}</div>}

      <div>{children}</div>

      {auditFooter && (
        <Card variant="outlined" padding="sm">
          <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>{auditFooter}</div>
        </Card>
      )}
    </div>
  );
};
