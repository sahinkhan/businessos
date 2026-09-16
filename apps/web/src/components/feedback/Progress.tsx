import React from 'react';

export interface ProgressProps {
  value?: number; // 0 to 100, undefined means indeterminate
  max?: number;
  label?: string;
  showValue?: boolean;
}

export const Progress: React.FC<ProgressProps> = ({
  value,
  max = 100,
  label,
  showValue = false,
}) => {
  const isIndeterminate = value === undefined;
  const percentage = isIndeterminate ? 0 : Math.min(100, Math.max(0, (value / max) * 100));

  return (
    <div style={{ width: '100%' }}>
      {(label || showValue) && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            marginBottom: '4px',
            fontSize: '0.8125rem',
          }}
        >
          {label && <span style={{ color: 'var(--color-text-secondary)' }}>{label}</span>}
          {showValue && !isIndeterminate && (
            <span style={{ color: 'var(--color-text-muted)' }}>{Math.round(percentage)}%</span>
          )}
        </div>
      )}
      <div
        role="progressbar"
        aria-valuenow={isIndeterminate ? undefined : value}
        aria-valuemin={0}
        aria-valuemax={max}
        style={{
          width: '100%',
          height: '6px',
          backgroundColor: 'var(--color-surface-subtle)',
          borderRadius: '9999px',
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        <div
          style={{
            height: '100%',
            backgroundColor: 'var(--color-action-primary)',
            borderRadius: '9999px',
            width: isIndeterminate ? '40%' : `${percentage}%`,
            transition: isIndeterminate ? 'none' : 'width 250ms ease',
            animation: isIndeterminate
              ? 'bos-progress-indeterminate 1.5s infinite ease-in-out'
              : 'none',
          }}
        />
        {isIndeterminate && (
          <style>
            {`@keyframes bos-progress-indeterminate { 0% { left: -40%; } 50% { left: 60%; } 100% { left: 100%; } }`}
          </style>
        )}
      </div>
    </div>
  );
};
