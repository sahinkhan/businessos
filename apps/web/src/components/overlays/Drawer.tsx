import React, { useEffect, useId, useRef } from 'react';
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
  closeLabel?: string;
}

export const Drawer: React.FC<DrawerProps> = ({
  isOpen,
  onClose,
  title,
  children,
  footer,
  placement = 'right',
  width = '380px',
  closeLabel = 'Close',
}) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!isOpen) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const focusable = () =>
      Array.from(
        panel?.querySelectorAll<HTMLElement>(
          'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
        ) ?? []
      );
    (focusable()[0] ?? panel)?.focus();
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'Tab') {
        const elements = focusable();
        if (elements.length === 0) {
          e.preventDefault();
          panel?.focus();
        } else if (e.shiftKey && document.activeElement === elements[0]) {
          e.preventDefault();
          elements[elements.length - 1].focus();
        } else if (!e.shiftKey && document.activeElement === elements[elements.length - 1]) {
          e.preventDefault();
          elements[0].focus();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      previouslyFocused?.focus();
    };
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
      aria-labelledby={title ? titleId : undefined}
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
        ref={panelRef}
        tabIndex={-1}
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
            id={titleId}
            style={{ fontSize: '1.0625rem', fontWeight: 600, color: 'var(--color-text-primary)' }}
          >
            {title}
          </div>
          <IconButton
            icon={<X size={18} />}
            aria-label={closeLabel}
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
