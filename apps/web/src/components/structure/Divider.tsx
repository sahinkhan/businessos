import React from 'react';

export interface DividerProps {
  orientation?: 'horizontal' | 'vertical';
  label?: string;
  style?: React.CSSProperties;
}

export const Divider: React.FC<DividerProps> = ({ orientation = 'horizontal', label, style }) => {
  if (orientation === 'vertical') {
    return (
      <div
        role="separator"
        aria-orientation="vertical"
        style={{
          width: '1px',
          backgroundColor: 'var(--color-border-subtle)',
          margin: '0 8px',
          alignSelf: 'stretch',
          ...style,
        }}
      />
    );
  }

  if (label) {
    return (
      <div
        role="separator"
        style={{
          display: 'flex',
          alignItems: 'center',
          width: '100%',
          margin: '16px 0',
          ...style,
        }}
      >
        <div style={{ flex: 1, height: '1px', backgroundColor: 'var(--color-border-subtle)' }} />
        <span
          style={{
            padding: '0 10px',
            fontSize: '0.75rem',
            color: 'var(--color-text-muted)',
            textTransform: 'uppercase',
          }}
        >
          {label}
        </span>
        <div style={{ flex: 1, height: '1px', backgroundColor: 'var(--color-border-subtle)' }} />
      </div>
    );
  }

  return (
    <hr
      role="separator"
      style={{
        border: 'none',
        borderTop: '1px solid var(--color-border-subtle)',
        margin: '16px 0',
        width: '100%',
        ...style,
      }}
    />
  );
};
