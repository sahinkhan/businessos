import React from 'react';

export interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: React.ReactNode;
  disabled?: boolean;
  'aria-label'?: string;
}

export const Switch: React.FC<SwitchProps> = ({
  checked,
  onChange,
  label,
  disabled,
  'aria-label': ariaLabel,
}) => {
  return (
    <label
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '8px',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.6 : 1,
        userSelect: 'none',
      }}
    >
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={ariaLabel || (typeof label === 'string' ? label : 'Toggle')}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        style={{
          width: '38px',
          height: '22px',
          backgroundColor: checked ? 'var(--color-action-primary)' : 'var(--color-border-default)',
          borderRadius: '9999px',
          border: 'none',
          position: 'relative',
          cursor: disabled ? 'not-allowed' : 'pointer',
          transition: 'background-color 200ms ease',
          padding: '2px',
          outline: 'none',
        }}
      >
        <span
          style={{
            display: 'block',
            width: '18px',
            height: '18px',
            backgroundColor: 'white',
            borderRadius: '50%',
            transform: checked ? 'translateX(16px)' : 'translateX(0px)',
            transition: 'transform 200ms ease',
            boxShadow: '0 1px 2px rgba(0,0,0,0.2)',
          }}
        />
      </button>
      {label && (
        <span style={{ fontSize: '0.875rem', color: 'var(--color-text-primary)' }}>{label}</span>
      )}
    </label>
  );
};
