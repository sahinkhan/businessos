import React, { forwardRef } from 'react';
import { Spinner } from '../feedback/Spinner';

export type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  isLoading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

const sizeStyles: Record<ButtonSize, { padding: string; fontSize: string; height: string }> = {
  sm: { padding: '4px 10px', fontSize: '0.8125rem', height: '30px' },
  md: { padding: '6px 14px', fontSize: '0.875rem', height: '36px' },
  lg: { padding: '8px 20px', fontSize: '1rem', height: '42px' },
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'secondary',
      size = 'md',
      isLoading = false,
      leftIcon,
      rightIcon,
      disabled,
      children,
      style,
      className = '',
      type = 'button',
      ...rest
    },
    ref
  ) => {
    const s = sizeStyles[size];

    const getBgColor = () => {
      if (variant === 'primary') return 'var(--color-action-primary)';
      if (variant === 'danger') return 'var(--color-action-danger)';
      if (variant === 'secondary') return 'var(--color-action-secondary)';
      return 'transparent';
    };

    const getTextColor = () => {
      if (variant === 'primary' || variant === 'danger') return 'var(--color-action-primary-text)';
      return 'var(--color-text-primary)';
    };

    const getBorder = () => {
      if (variant === 'outline') return '1px solid var(--color-border-default)';
      if (variant === 'secondary') return '1px solid var(--color-border-subtle)';
      return '1px solid transparent';
    };

    const combinedStyle: React.CSSProperties = {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '6px',
      borderRadius: '6px',
      fontWeight: 500,
      cursor: disabled || isLoading ? 'not-allowed' : 'pointer',
      opacity: disabled ? 0.55 : 1,
      transition: 'all 150ms cubic-bezier(0.4, 0, 0.2, 1)',
      outline: 'none',
      whiteSpace: 'nowrap',
      userSelect: 'none',
      backgroundColor: getBgColor(),
      color: getTextColor(),
      border: getBorder(),
      padding: s.padding,
      fontSize: s.fontSize,
      height: s.height,
      ...style,
    };

    return (
      <button
        ref={ref}
        type={type}
        disabled={disabled || isLoading}
        aria-busy={isLoading ? 'true' : undefined}
        style={combinedStyle}
        className={`bos-button bos-button--${variant} bos-button--${size} ${className}`}
        {...rest}
      >
        {isLoading ? <Spinner size={size === 'sm' ? 'xs' : 'sm'} color="currentColor" /> : leftIcon}
        {children && <span>{children}</span>}
        {!isLoading && rightIcon}
      </button>
    );
  }
);
Button.displayName = 'Button';
