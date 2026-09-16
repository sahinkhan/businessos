import React from 'react';

export interface StackProps extends React.HTMLAttributes<HTMLDivElement> {
  direction?: 'row' | 'column';
  gap?: number | string;
  align?: 'flex-start' | 'center' | 'flex-end' | 'stretch';
  justify?: 'flex-start' | 'center' | 'flex-end' | 'space-between' | 'space-around';
  wrap?: boolean;
}

export const Stack: React.FC<StackProps> = ({
  direction = 'column',
  gap = 12,
  align = 'stretch',
  justify = 'flex-start',
  wrap = false,
  children,
  style,
  ...rest
}) => {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: direction,
        gap: typeof gap === 'number' ? `${gap}px` : gap,
        alignItems: align,
        justifyContent: justify,
        flexWrap: wrap ? 'wrap' : 'nowrap',
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
};
