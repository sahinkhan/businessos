import React, { forwardRef } from 'react';
import { TextInput, TextInputProps } from './TextInput';

export interface NumberInputProps extends Omit<TextInputProps, 'onChange' | 'value'> {
  value?: number | '';
  onChange?: (val: number | '') => void;
  min?: number;
  max?: number;
  step?: number;
}

export const NumberInput = forwardRef<HTMLInputElement, NumberInputProps>(
  ({ value, onChange, min, max, step = 1, ...rest }, ref) => {
    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const v = e.target.value;
      if (v === '') {
        onChange?.('');
        return;
      }
      const parsed = parseFloat(v);
      if (!isNaN(parsed)) {
        if (min !== undefined && parsed < min) {
          onChange?.(min);
        } else if (max !== undefined && parsed > max) {
          onChange?.(max);
        } else {
          onChange?.(parsed);
        }
      }
    };

    return (
      <TextInput
        ref={ref}
        type="number"
        min={min}
        max={max}
        step={step}
        value={value ?? ''}
        onChange={handleChange}
        {...rest}
      />
    );
  }
);
NumberInput.displayName = 'NumberInput';
