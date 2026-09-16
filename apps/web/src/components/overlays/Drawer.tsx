import React, { useEffect } from 'react';
import { X } from 'lucide-react';
import { IconButton } from '../actions/IconButton';

export type DrawerPlacement = 'left' | 'right' | 'bottom';

export interface DrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  placement?: DrawerPlacement;
  width?: string;
}

export const Drawer: React.FC<DrawerProps> = ({
  isOpen,
  onClose,
  title,
  children,
  footer,
  placement = 'right',
  width = '380px',
}) => {
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const placementStyles: React.CSSProperties =
    placement === 'right'
      ? { top: 0, right: 0, bottom: 0, width, height: '100%' }
      : placement === 'left'
        ? { top: 0, left: 0, bottom: 0, width, height: '100%' }
        : { bottom: 0, left: 0, right: 0, height: width, width: '100%' };

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'var(--color-surface-overlay)',
        zIndex: 1350,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          position: 'absolute',
          backgroundColor: 'var(--color-surface-card)',
          borderLeft: placement === 'right' ? '1px solid var(--color-border-subtle)' : undefined,
          borderRight: placement === 'left' ? '1px solid var(--color-border-subtle)' : undefined,
          boxShadow: 'var(--shadow-modal)',
          display: 'flex',
          flexDirection: 'column',
          ...placementStyles,
        }}
      >
        <div
          style={{
            padding: '16px 20px',
            borderBottom: '1px solid var(--color-border-subtle)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div
            style={{ fontSize: '1.0625rem', fontWeight: 600, color: 'var(--color-text-primary)' }}
          >
            {title}
          </div>
          <IconButton
            icon={<X size={18} />}
            aria-label="Close drawer"
            variant="ghost"
            size="sm"
            onClick={onClose}
          />
        </div>
        <div style={{ padding: '20px', overflowY: 'auto', flex: 1 }}>{children}</div>
        {footer && (
          <div
            style={{
              padding: '14px 20px',
              borderTop: '1px solid var(--color-border-subtle)',
              backgroundColor: 'var(--color-surface-subtle)',
              display: 'flex',
              justifyContent: 'flex-end',
              gap: '8px',
            }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>
  );
};
