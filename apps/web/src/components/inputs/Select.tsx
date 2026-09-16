import React, { forwardRef } from 'react';

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  options: SelectOption[];
  error?: boolean;
  placeholder?: string;
  inputSize?: 'sm' | 'md' | 'lg';
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  (
    { options, error, placeholder, inputSize = 'md', disabled, style, className = '', ...rest },
    ref
  ) => {
    const heights = { sm: '30px', md: '36px', lg: '42px' };
    const fontSizes = { sm: '0.8125rem', md: '0.875rem', lg: '1rem' };

    return (
      <select
        ref={ref}
        disabled={disabled}
        className={`bos-select ${className}`}
        style={{
          width: '100%',
          height: heights[inputSize],
          fontSize: fontSizes[inputSize],
          padding: '0 10px',
          borderRadius: '6px',
          backgroundColor: disabled ? 'var(--color-surface-subtle)' : 'var(--color-surface-card)',
          border: `1px solid ${error ? 'var(--color-status-danger)' : 'var(--color-border-default)'}`,
          color: 'var(--color-text-primary)',
          outline: 'none',
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.6 : 1,
          ...style,
        }}
        {...rest}
      >
        {placeholder && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map((opt) => (
          <option key={opt.value} value={opt.value} disabled={opt.disabled}>
            {opt.label}
          </option>
        ))}
      </select>
    );
  }
);
Select.displayName = 'Select';
