import React, { useState } from 'react';
import { AlertOctagon, ChevronDown, ChevronUp, RefreshCw } from 'lucide-react';
import { Button } from '../actions/Button';
import { useI18nText } from '../../i18n/I18nContext';

export interface ErrorStateProps {
  title?: string;
  message?: string;
  error?: Error | unknown;
  onRetry?: () => void;
  style?: React.CSSProperties;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title,
  message,
  error,
  onRetry,
  style,
}) => {
  const [showDetails, setShowDetails] = useState(false);
  const { t } = useI18nText();
  const resolvedTitle = title ?? t('errors.generic_title');
  const resolvedMessage = message ?? t('errors.generic_body');

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '48px 24px',
        textAlign: 'center',
        ...style,
      }}
    >
      <div
        style={{
          width: '56px',
          height: '56px',
          borderRadius: '50%',
          backgroundColor: 'var(--color-status-danger-bg)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--color-status-danger)',
          marginBottom: '16px',
        }}
      >
        <AlertOctagon size={28} />
      </div>
      <h3
        style={{
          fontSize: '1.125rem',
          fontWeight: 600,
          color: 'var(--color-text-primary)',
          marginBottom: '6px',
        }}
      >
        {resolvedTitle}
      </h3>
      <p
        style={{
          fontSize: '0.875rem',
          color: 'var(--color-text-secondary)',
          maxWidth: '420px',
          marginBottom: '16px',
        }}
      >
        {resolvedMessage}
      </p>
      {onRetry && (
        <Button variant="primary" size="md" leftIcon={<RefreshCw size={16} />} onClick={onRetry}>
          {t('common.retry')}
        </Button>
      )}
      {Boolean(error) && (
        <div style={{ marginTop: '16px', maxWidth: '500px', width: '100%' }}>
          <button
            type="button"
            onClick={() => setShowDetails(!showDetails)}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--color-text-muted)',
              fontSize: '0.8125rem',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            {showDetails ? t('errors.hide_details') : t('errors.show_details')}
            {showDetails ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          {showDetails && (
            <pre
              style={{
                marginTop: '8px',
                padding: '12px',
                borderRadius: '6px',
                backgroundColor: 'var(--color-surface-subtle)',
                color: 'var(--color-status-danger)',
                fontSize: '0.75rem',
                textAlign: 'left',
                overflowX: 'auto',
                whiteSpace: 'pre-wrap',
                fontFamily: 'var(--font-mono, monospace)',
              }}
            >
              {error instanceof Error ? error.stack || error.message : String(error)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
};
