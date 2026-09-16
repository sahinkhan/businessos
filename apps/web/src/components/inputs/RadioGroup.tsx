import React from 'react';

export interface RadioOption {
  value: string;
  label: React.ReactNode;
  description?: string;
  disabled?: boolean;
}

export interface RadioGroupProps {
  name: string;
  value: string;
  onChange: (value: string) => void;
  options: RadioOption[];
  orientation?: 'vertical' | 'horizontal';
  disabled?: boolean;
}

export const RadioGroup: React.FC<RadioGroupProps> = ({
  name,
  value,
  onChange,
  options,
  orientation = 'vertical',
  disabled: groupDisabled,
}) => {
  return (
    <div
      role="radiogroup"
      style={{
        display: 'flex',
        flexDirection: orientation === 'vertical' ? 'column' : 'row',
        gap: orientation === 'vertical' ? '8px' : '16px',
      }}
    >
      {options.map((opt) => {
        const isDisabled = groupDisabled || opt.disabled;
        const optId = `${name}_${opt.value}`;

        return (
          <label
            key={opt.value}
            htmlFor={optId}
            style={{
              display: 'inline-flex',
              alignItems: 'flex-start',
              gap: '8px',
              cursor: isDisabled ? 'not-allowed' : 'pointer',
              opacity: isDisabled ? 0.6 : 1,
              userSelect: 'none',
            }}
          >
            <input
              id={optId}
              type="radio"
              name={name}
              value={opt.value}
              checked={value === opt.value}
              disabled={isDisabled}
              onChange={() => onChange(opt.value)}
              style={{
                marginTop: '3px',
                cursor: isDisabled ? 'not-allowed' : 'pointer',
                accentColor: 'var(--color-action-primary)',
              }}
            />
            <div>
              <div
                style={{
                  fontSize: '0.875rem',
                  fontWeight: 500,
                  color: 'var(--color-text-primary)',
                }}
              >
                {opt.label}
              </div>
              {opt.description && (
                <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                  {opt.description}
                </div>
              )}
            </div>
          </label>
        );
      })}
    </div>
  );
};
