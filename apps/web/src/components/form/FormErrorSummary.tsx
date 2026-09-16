import React from 'react';
import { AlertCircle } from 'lucide-react';

export interface FormErrorSummaryProps {
  errors: Array<{ fieldId: string; label: string; message: string }>;
}

export const FormErrorSummary: React.FC<FormErrorSummaryProps> = ({ errors }) => {
  if (errors.length === 0) return null;

  const focusField = (fieldId: string) => {
    const el = document.getElementById(fieldId);
    if (el) {
      el.focus();
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  };

  return (
    <div
      role="alert"
      style={{
        padding: '12px 16px',
        borderRadius: '6px',
        backgroundColor: 'var(--color-status-danger-bg)',
        border: '1px solid var(--color-status-danger-border)',
        marginBottom: '20px',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          color: 'var(--color-status-danger)',
          fontWeight: 600,
          marginBottom: '6px',
        }}
      >
        <AlertCircle size={18} />
        <span>Please correct the following errors:</span>
      </div>
      <ul style={{ margin: '0 0 0 24px', padding: 0, fontSize: '0.875rem' }}>
        {errors.map((err, i) => (
          <li key={i} style={{ marginBottom: '4px' }}>
            <button
              type="button"
              onClick={() => focusField(err.fieldId)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--color-status-danger)',
                textDecoration: 'underline',
                cursor: 'pointer',
                padding: 0,
                textAlign: 'left',
              }}
            >
              <strong>{err.label}:</strong> {err.message}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
};
