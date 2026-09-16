import React, { forwardRef, useEffect, useRef } from 'react';

export interface CheckboxProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label?: React.ReactNode;
  description?: string;
  indeterminate?: boolean;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  ({ label, description, indeterminate, disabled, className = '', id, ...rest }, ref) => {
    const internalRef = useRef<HTMLInputElement | null>(null);
    const resolvedId = id || 'bos_cb_' + Math.random().toString(36).substring(2, 8);

    useEffect(() => {
      const target =
        ref && typeof ref === 'object' && 'current' in ref ? ref.current : internalRef.current;
      if (target) {
        target.indeterminate = Boolean(indeterminate);
      }
    }, [indeterminate, ref]);

    return (
      <label
        htmlFor={resolvedId}
        style={{
          display: 'inline-flex',
          alignItems: 'flex-start',
          gap: '8px',
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.6 : 1,
          userSelect: 'none',
        }}
        className={`bos-checkbox-label ${className}`}
      >
        <input
          ref={(node) => {
            internalRef.current = node;
            if (typeof ref === 'function') ref(node);
            else if (ref) ref.current = node;
          }}
          id={resolvedId}
          type="checkbox"
          disabled={disabled}
          style={{
            marginTop: '3px',
            cursor: disabled ? 'not-allowed' : 'pointer',
            accentColor: 'var(--color-action-primary)',
          }}
          {...rest}
        />
        {label && (
          <div>
            <div
              style={{ fontSize: '0.875rem', fontWeight: 500, color: 'var(--color-text-primary)' }}
            >
              {label}
            </div>
            {description && (
              <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                {description}
              </div>
            )}
          </div>
        )}
      </label>
    );
  }
);
Checkbox.displayName = 'Checkbox';
