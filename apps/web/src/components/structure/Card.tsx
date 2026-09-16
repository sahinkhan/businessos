import React from 'react';

export interface CardProps {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
  variant?: 'default' | 'outlined' | 'elevated';
  padding?: 'none' | 'sm' | 'md' | 'lg';
  className?: string;
  style?: React.CSSProperties;
}

const paddingMap = {
  none: '0px',
  sm: '12px',
  md: '16px',
  lg: '24px',
};

export const Card: React.FC<CardProps> = ({
  title,
  subtitle,
  actions,
  footer,
  children,
  variant = 'default',
  padding = 'md',
  className = '',
  style,
}) => {
  const pad = paddingMap[padding];

  return (
    <div
      className={`bos-card bos-card--${variant} ${className}`}
      style={{
        backgroundColor: 'var(--color-surface-card)',
        borderRadius: '8px',
        border: '1px solid var(--color-border-subtle)',
        boxShadow: variant === 'elevated' ? 'var(--shadow-dropdown)' : 'var(--shadow-card)',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        ...style,
      }}
    >
      {(title || subtitle || actions) && (
        <div
          style={{
            padding: `${pad} ${pad} 12px ${pad}`,
            borderBottom: '1px solid var(--color-border-subtle)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
          }}
        >
          <div>
            {title && (
              <h3 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
                {title}
              </h3>
            )}
            {subtitle && (
              <p
                style={{
                  fontSize: '0.8125rem',
                  color: 'var(--color-text-secondary)',
                  marginTop: '2px',
                }}
              >
                {subtitle}
              </p>
            )}
          </div>
          {actions && (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>{actions}</div>
          )}
        </div>
      )}
      <div style={{ padding: pad, flex: 1 }}>{children}</div>
      {footer && (
        <div
          style={{
            padding: `12px ${pad}`,
            borderTop: '1px solid var(--color-border-subtle)',
            backgroundColor: 'var(--color-surface-subtle)',
            fontSize: '0.875rem',
          }}
        >
          {footer}
        </div>
      )}
    </div>
  );
};
