import React from 'react';
import './Grid.css';

export interface GridProps extends React.HTMLAttributes<HTMLDivElement> {
  columns?: number | { sm?: number; md?: number; lg?: number; xl?: number };
  gap?: number | string;
}

export const Grid: React.FC<GridProps> = ({
  columns = 1,
  gap = 16,
  children,
  style,
  className = '',
  ...rest
}) => {
  const sm = typeof columns === 'number' ? columns : (columns.sm ?? 1);
  const md = typeof columns === 'number' ? columns : (columns.md ?? sm);
  const lg = typeof columns === 'number' ? columns : (columns.lg ?? md);
  const xl = typeof columns === 'number' ? columns : (columns.xl ?? lg);

  return (
    <div
      className={`bos-grid ${className}`}
      style={
        {
          display: 'grid',
          '--bos-grid-sm': sm,
          '--bos-grid-md': md,
          '--bos-grid-lg': lg,
          '--bos-grid-xl': xl,
          gap: typeof gap === 'number' ? `${gap}px` : gap,
          width: '100%',
          ...style,
        } as React.CSSProperties
      }
      {...rest}
    >
      {children}
    </div>
  );
};
