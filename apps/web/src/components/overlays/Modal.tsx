import React, { useEffect } from 'react';
import { X } from 'lucide-react';
import { IconButton } from '../actions/IconButton';

export type ModalSize = 'sm' | 'md' | 'lg' | 'xl' | 'full';

export interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  size?: ModalSize;
  closeOnBackdrop?: boolean;
}

const sizeWidths: Record<ModalSize, string> = {
  sm: '400px',
  md: '540px',
  lg: '720px',
  xl: '960px',
  full: '95vw',
};

export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  description,
  children,
  footer,
  size = 'md',
  closeOnBackdrop = true,
}) => {
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? 'bos-modal-title' : undefined}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'var(--color-surface-overlay)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1300,
        padding: '16px',
        animation: 'bos-fade-in 150ms ease',
      }}
      onClick={(e) => {
        if (closeOnBackdrop && e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        style={{
          backgroundColor: 'var(--color-surface-card)',
          borderRadius: '10px',
          border: '1px solid var(--color-border-subtle)',
          boxShadow: 'var(--shadow-modal)',
          maxWidth: sizeWidths[size],
          width: '100%',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          animation: 'bos-scale-in 150ms ease',
        }}
      >
        {(title || description) && (
          <div
            style={{
              padding: '16px 20px',
              borderBottom: '1px solid var(--color-border-subtle)',
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'space-between',
            }}
          >
            <div>
              {title && (
                <h2
                  id="bos-modal-title"
                  style={{
                    fontSize: '1.125rem',
                    fontWeight: 600,
                    color: 'var(--color-text-primary)',
                  }}
                >
                  {title}
                </h2>
              )}
              {description && (
                <p
                  style={{
                    fontSize: '0.8125rem',
                    color: 'var(--color-text-secondary)',
                    marginTop: '2px',
                  }}
                >
                  {description}
                </p>
              )}
            </div>
            <IconButton
              icon={<X size={18} />}
              aria-label="Close dialog"
              variant="ghost"
              size="sm"
              onClick={onClose}
            />
          </div>
        )}
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
