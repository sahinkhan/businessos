import React, { useState, useRef, useEffect } from 'react';
import { Button, ButtonProps } from './Button';
import { ChevronDown } from 'lucide-react';
import { useI18nText } from '../../i18n/I18nContext';

export interface SplitButtonItem {
  id: string;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}

export interface SplitButtonProps extends ButtonProps {
  menuItems: SplitButtonItem[];
}

export const SplitButton: React.FC<SplitButtonProps> = ({
  menuItems,
  children,
  onClick,
  disabled,
  variant = 'primary',
  size = 'md',
  ...rest
}) => {
  const { t } = useI18nText();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, []);

  return (
    <div ref={containerRef} style={{ position: 'relative', display: 'inline-flex' }}>
      <Button
        variant={variant}
        size={size}
        onClick={onClick}
        disabled={disabled}
        style={{ borderTopRightRadius: 0, borderBottomRightRadius: 0, borderRight: 'none' }}
        {...rest}
      >
        {children}
      </Button>
      <Button
        variant={variant}
        size={size}
        disabled={disabled}
        onClick={() => setIsOpen(!isOpen)}
        aria-haspopup="true"
        aria-expanded={isOpen}
        aria-label={t('controls.more_options')}
        style={{
          borderTopLeftRadius: 0,
          borderBottomLeftRadius: 0,
          padding: '0 6px',
          minWidth: '28px',
        }}
      >
        <ChevronDown size={14} />
      </Button>
      {isOpen && (
        <div
          role="menu"
          style={{
            position: 'absolute',
            top: '100%',
            right: 0,
            marginTop: '4px',
            backgroundColor: 'var(--color-surface-card)',
            border: '1px solid var(--color-border-subtle)',
            borderRadius: '6px',
            boxShadow: 'var(--shadow-dropdown)',
            zIndex: 1000,
            minWidth: '160px',
            padding: '4px 0',
          }}
        >
          {menuItems.map((item) => (
            <button
              key={item.id}
              role="menuitem"
              disabled={item.disabled}
              onClick={() => {
                item.onClick();
                setIsOpen(false);
              }}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                padding: '8px 12px',
                fontSize: '0.875rem',
                backgroundColor: 'transparent',
                border: 'none',
                color: item.disabled ? 'var(--color-text-muted)' : 'var(--color-text-primary)',
                cursor: item.disabled ? 'not-allowed' : 'pointer',
              }}
              onMouseEnter={(e) => {
                if (!item.disabled)
                  e.currentTarget.style.backgroundColor = 'var(--color-surface-subtle)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'transparent';
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
