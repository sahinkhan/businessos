import React, { forwardRef } from 'react';

export interface TextInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  error?: boolean;
  leftElement?: React.ReactNode;
  rightElement?: React.ReactNode;
  inputSize?: 'sm' | 'md' | 'lg';
}

const sizePadding = {
  sm: { py: '4px', px: '8px', fontSize: '0.8125rem', height: '30px' },
  md: { py: '6px', px: '10px', fontSize: '0.875rem', height: '36px' },
  lg: { py: '8px', px: '12px', fontSize: '1rem', height: '42px' },
};

export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(
  (
    {
      error,
      leftElement,
      rightElement,
      inputSize = 'md',
      disabled,
      readOnly,
      className = '',
      style,
      ...rest
    },
    ref
  ) => {
    const s = sizePadding[inputSize];

    return (
      <div
        className={`bos-text-input-container ${className}`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          position: 'relative',
          width: '100%',
          backgroundColor: disabled ? 'var(--color-surface-subtle)' : 'var(--color-surface-card)',
          border: `1px solid ${error ? 'var(--color-status-danger)' : 'var(--color-border-default)'}`,
          borderRadius: '6px',
          transition: 'border-color 150ms ease, box-shadow 150ms ease',
          height: s.height,
          paddingLeft: leftElement ? '8px' : '0',
          paddingRight: rightElement ? '8px' : '0',
          opacity: disabled ? 0.6 : 1,
          ...style,
        }}
      >
        {leftElement && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              color: 'var(--color-text-muted)',
              marginRight: '6px',
            }}
          >
            {leftElement}
          </div>
        )}
        <input
          ref={ref}
          disabled={disabled}
          readOnly={readOnly}
          style={{
            flex: 1,
            width: '100%',
            height: '100%',
            background: 'transparent',
            border: 'none',
            outline: 'none',
            padding: `${s.py} ${s.px}`,
            fontSize: s.fontSize,
            color: 'var(--color-text-primary)',
            cursor: disabled ? 'not-allowed' : readOnly ? 'default' : 'text',
          }}
          {...rest}
        />
        {rightElement && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              color: 'var(--color-text-muted)',
              marginLeft: '6px',
            }}
          >
            {rightElement}
          </div>
        )}
      </div>
    );
  }
);
TextInput.displayName = 'TextInput';
