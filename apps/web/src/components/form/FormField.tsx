import React from 'react';

export interface FormFieldProps {
  id?: string;
  label?: React.ReactNode;
  required?: boolean;
  optional?: boolean;
  helpText?: string;
  error?: string;
  children: React.ReactElement;
  className?: string;
}

export const FormField: React.FC<FormFieldProps> = ({
  id: customId,
  label,
  required,
  optional,
  helpText,
  error,
  children,
  className = '',
}) => {
  const childId = children.props.id;
  const fieldId = customId || childId || 'field_' + Math.random().toString(36).substring(2, 9);
  const helpId = `${fieldId}-help`;
  const errorId = `${fieldId}-error`;

  const ariaDescribedBy = [
    helpText ? helpId : null,
    error ? errorId : null,
    children.props['aria-describedby'],
  ]
    .filter(Boolean)
    .join(' ');

  const clonedChild = React.cloneElement(children, {
    id: fieldId,
    'aria-invalid': error ? true : undefined,
    'aria-required': required ? 'true' : undefined,
    'aria-describedby': ariaDescribedBy || undefined,
    error: Boolean(error) || children.props.error,
  });

  return (
    <div className={`bos-form-field ${className}`} style={{ marginBottom: '16px' }}>
      {label && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '6px',
          }}
        >
          <label
            htmlFor={fieldId}
            style={{ fontSize: '0.875rem', fontWeight: 500, color: 'var(--color-text-primary)' }}
          >
            {label}
            {required && (
              <span
                aria-hidden="true"
                style={{ color: 'var(--color-status-danger)', marginLeft: '4px' }}
              >
                *
              </span>
            )}
          </label>
          {optional && !required && (
            <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>Optional</span>
          )}
        </div>
      )}
      {clonedChild}
      {helpText && !error && (
        <div
          id={helpId}
          style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', marginTop: '4px' }}
        >
          {helpText}
        </div>
      )}
      {error && (
        <div
          id={errorId}
          role="alert"
          style={{
            fontSize: '0.75rem',
            color: 'var(--color-status-danger)',
            marginTop: '4px',
            fontWeight: 500,
          }}
        >
          {error}
        </div>
      )}
    </div>
  );
};
