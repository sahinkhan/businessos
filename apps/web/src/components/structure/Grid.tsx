import React from 'react';

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
  const colCount = typeof columns === 'number' ? columns : columns.md || 1;

  return (
    <div
      className={`bos-grid ${className}`}
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${colCount}, minmax(0, 1fr))`,
        gap: typeof gap === 'number' ? `${gap}px` : gap,
        width: '100%',
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
};
