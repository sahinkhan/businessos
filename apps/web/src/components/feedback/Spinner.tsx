import React from 'react';

export type SpinnerSize = 'xs' | 'sm' | 'md' | 'lg';

export interface SpinnerProps {
  size?: SpinnerSize | number;
  color?: string;
  className?: string;
}

const sizeMap: Record<SpinnerSize, number> = {
  xs: 14,
  sm: 18,
  md: 24,
  lg: 36,
};

export const Spinner: React.FC<SpinnerProps> = ({
  size = 'md',
  color = 'var(--color-action-primary)',
  className = '',
}) => {
  const pixelSize = typeof size === 'number' ? size : sizeMap[size];

  return (
    <svg
      role="status"
      aria-live="polite"
      aria-label="Loading"
      className={`bos-spinner ${className}`}
      width={pixelSize}
      height={pixelSize}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{
        animation: 'bos-spin 0.8s linear infinite',
        display: 'inline-block',
      }}
    >
      <style>
        {`@keyframes bos-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}
      </style>
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
  );
};
