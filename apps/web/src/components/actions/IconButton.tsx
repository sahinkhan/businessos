import React, { forwardRef } from 'react';
import { Button, ButtonProps } from './Button';

export interface IconButtonProps extends Omit<ButtonProps, 'leftIcon' | 'rightIcon' | 'children'> {
  icon: React.ReactNode;
  'aria-label': string;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ icon, 'aria-label': ariaLabel, size = 'md', style, ...rest }, ref) => {
    const squareSizes = {
      sm: '30px',
      md: '36px',
      lg: '42px',
    };

    return (
      <Button
        ref={ref}
        size={size}
        aria-label={ariaLabel}
        style={{
          width: squareSizes[size],
          height: squareSizes[size],
          padding: 0,
          ...style,
        }}
        {...rest}
      >
        {icon}
      </Button>
    );
  }
);
IconButton.displayName = 'IconButton';
