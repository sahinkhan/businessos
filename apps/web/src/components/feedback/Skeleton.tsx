import React from 'react';

export interface SkeletonProps {
  variant?: 'text' | 'rectangular' | 'circular';
  width?: string | number;
  height?: string | number;
  className?: string;
  style?: React.CSSProperties;
}

export const Skeleton: React.FC<SkeletonProps> = ({
  variant = 'text',
  width = '100%',
  height,
  className = '',
  style,
}) => {
  const getDefaultHeight = () => {
    if (height) return height;
    if (variant === 'text') return '1rem';
    if (variant === 'circular') return width || '40px';
    return '100px';
  };

  return (
    <div
      aria-hidden="true"
      className={`bos-skeleton ${className}`}
      style={{
        width,
        height: getDefaultHeight(),
        borderRadius: variant === 'circular' ? '9999px' : variant === 'text' ? '4px' : '6px',
        backgroundColor: 'var(--color-surface-subtle)',
        animation: 'bos-pulse 1.6s ease-in-out 0.5s infinite',
        display: 'inline-block',
        ...style,
      }}
    >
      <style>{`@keyframes bos-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }`}</style>
    </div>
  );
};
