import React, { forwardRef } from 'react';

export interface TextAreaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: boolean;
  showCount?: boolean;
}

export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(
  (
    { error, disabled, readOnly, showCount, maxLength, value, className = '', style, ...rest },
    ref
  ) => {
    const currentLength = typeof value === 'string' ? value.length : 0;

    return (
      <div style={{ position: 'relative', width: '100%' }}>
        <textarea
          ref={ref}
          disabled={disabled}
          readOnly={readOnly}
          maxLength={maxLength}
          value={value}
          className={`bos-textarea ${className}`}
          style={{
            width: '100%',
            minHeight: '80px',
            padding: '8px 12px',
            fontSize: '0.875rem',
            color: 'var(--color-text-primary)',
            backgroundColor: disabled ? 'var(--color-surface-subtle)' : 'var(--color-surface-card)',
            border: `1px solid ${error ? 'var(--color-status-danger)' : 'var(--color-border-default)'}`,
            borderRadius: '6px',
            outline: 'none',
            resize: 'vertical',
            opacity: disabled ? 0.6 : 1,
            cursor: disabled ? 'not-allowed' : 'text',
            ...style,
          }}
          {...rest}
        />
        {showCount && maxLength && (
          <div
            style={{
              fontSize: '0.75rem',
              color: 'var(--color-text-muted)',
              textAlign: 'right',
              marginTop: '2px',
            }}
          >
            {currentLength} / {maxLength}
          </div>
        )}
      </div>
    );
  }
);
TextArea.displayName = 'TextArea';
