import React, { useState, useRef, useEffect } from 'react';

export interface PopoverProps {
  trigger: (props: { isOpen: boolean; toggle: () => void }) => React.ReactNode;
  children: (props: { close: () => void }) => React.ReactNode;
  align?: 'left' | 'right';
}

export const Popover: React.FC<PopoverProps> = ({ trigger, children, align = 'left' }) => {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, []);

  return (
    <div ref={containerRef} style={{ position: 'relative', display: 'inline-block' }}>
      {trigger({ isOpen, toggle: () => setIsOpen(!isOpen) })}
      {isOpen && (
        <div
          role="dialog"
          style={{
            position: 'absolute',
            top: '100%',
            left: align === 'left' ? 0 : 'auto',
            right: align === 'right' ? 0 : 'auto',
            marginTop: '6px',
            backgroundColor: 'var(--color-surface-card)',
            border: '1px solid var(--color-border-subtle)',
            borderRadius: '8px',
            boxShadow: 'var(--shadow-dropdown)',
            zIndex: 1400,
            padding: '12px',
          }}
        >
          {children({ close: () => setIsOpen(false) })}
        </div>
      )}
    </div>
  );
};
