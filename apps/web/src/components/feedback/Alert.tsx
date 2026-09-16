import React from 'react';
import { AlertCircle, CheckCircle2, Info, AlertTriangle, X } from 'lucide-react';

export type AlertSeverity = 'info' | 'success' | 'warning' | 'danger';

export interface AlertProps {
  severity?: AlertSeverity;
  title?: string;
  children: React.ReactNode;
  onDismiss?: () => void;
  action?: React.ReactNode;
  className?: string;
}

const severityConfig: Record<
  AlertSeverity,
  { bg: string; border: string; text: string; icon: React.ReactNode }
> = {
  info: {
    bg: 'var(--color-status-info-bg)',
    border: 'var(--color-status-info-border)',
    text: 'var(--color-status-info)',
    icon: <Info size={18} />,
  },
  success: {
    bg: 'var(--color-status-success-bg)',
    border: 'var(--color-status-success-border)',
    text: 'var(--color-status-success)',
    icon: <CheckCircle2 size={18} />,
  },
  warning: {
    bg: 'var(--color-status-warning-bg)',
    border: 'var(--color-status-warning-border)',
    text: 'var(--color-status-warning)',
    icon: <AlertTriangle size={18} />,
  },
  danger: {
    bg: 'var(--color-status-danger-bg)',
    border: 'var(--color-status-danger-border)',
    text: 'var(--color-status-danger)',
    icon: <AlertCircle size={18} />,
  },
};

export const Alert: React.FC<AlertProps> = ({
  severity = 'info',
  title,
  children,
  onDismiss,
  action,
  className = '',
}) => {
  const conf = severityConfig[severity];

  return (
    <div
      role="alert"
      className={`bos-alert bos-alert--${severity} ${className}`}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: '12px',
        padding: '12px 16px',
        borderRadius: '6px',
        backgroundColor: conf.bg,
        border: `1px solid ${conf.border}`,
        color: 'var(--color-text-primary)',
        fontSize: '0.875rem',
      }}
    >
      <div style={{ color: conf.text, flexShrink: 0, marginTop: '2px' }}>{conf.icon}</div>
      <div style={{ flex: 1 }}>
        {title && <div style={{ fontWeight: 600, marginBottom: '2px' }}>{title}</div>}
        <div>{children}</div>
        {action && <div style={{ marginTop: '8px' }}>{action}</div>}
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss alert"
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--color-text-muted)',
            padding: '2px',
            display: 'inline-flex',
            borderRadius: '4px',
          }}
        >
          <X size={16} />
        </button>
      )}
    </div>
  );
};
