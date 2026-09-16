import React, { forwardRef } from 'react';
import { TextInput, TextInputProps } from './TextInput';

export interface MoneyInputProps extends Omit<TextInputProps, 'onChange' | 'value'> {
  value?: number | '';
  currency?: string;
  onValueChange?: (val: number | '', currency: string) => void;
  currencies?: string[];
  onCurrencyChange?: (currency: string) => void;
}

export const MoneyInput = forwardRef<HTMLInputElement, MoneyInputProps>(
  (
    {
      value,
      currency = 'USD',
      onValueChange,
      currencies = ['USD', 'EUR', 'GBP', 'SAR', 'AED'],
      onCurrencyChange,
      disabled,
      ...rest
    },
    ref
  ) => {
    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const raw = e.target.value;
      if (raw === '') {
        onValueChange?.('', currency);
        return;
      }
      const parsed = parseFloat(raw);
      if (!isNaN(parsed)) {
        onValueChange?.(parsed, currency);
      }
    };

    const left = (
      <select
        value={currency}
        disabled={disabled}
        onChange={(e) => {
          onCurrencyChange?.(e.target.value);
          onValueChange?.(value ?? '', e.target.value);
        }}
        aria-label="Currency"
        style={{
          border: 'none',
          background: 'transparent',
          fontSize: '0.8125rem',
          fontWeight: 600,
          color: 'var(--color-text-secondary)',
          outline: 'none',
          cursor: disabled ? 'not-allowed' : 'pointer',
        }}
      >
        {currencies.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    );

    return (
      <TextInput
        ref={ref}
        type="number"
        step="0.01"
        disabled={disabled}
        leftElement={left}
        value={value ?? ''}
        onChange={handleChange}
        placeholder="0.00"
        style={{ textAlign: 'right' }}
        {...rest}
      />
    );
  }
);
MoneyInput.displayName = 'MoneyInput';
