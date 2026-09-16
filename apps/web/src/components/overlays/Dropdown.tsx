import React, { useState, useRef, useEffect } from 'react';

export interface DropdownItem {
  id: string;
  label: React.ReactNode;
  icon?: React.ReactNode;
  danger?: boolean;
  disabled?: boolean;
  onClick: () => void;
}

export interface DropdownProps {
  trigger: React.ReactNode;
  items: (DropdownItem | { divider: true })[];
  align?: 'left' | 'right';
}

export const Dropdown: React.FC<DropdownProps> = ({ trigger, items, align = 'right' }) => {
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
      <div onClick={() => setIsOpen(!isOpen)}>{trigger}</div>
      {isOpen && (
        <div
          role="menu"
          style={{
            position: 'absolute',
            top: '100%',
            left: align === 'left' ? 0 : 'auto',
            right: align === 'right' ? 0 : 'auto',
            marginTop: '4px',
            backgroundColor: 'var(--color-surface-card)',
            border: '1px solid var(--color-border-subtle)',
            borderRadius: '6px',
            boxShadow: 'var(--shadow-dropdown)',
            zIndex: 1000,
            minWidth: '180px',
            padding: '4px 0',
          }}
        >
          {items.map((item, idx) => {
            if ('divider' in item) {
              return (
                <div
                  key={`div-${idx}`}
                  style={{
                    height: '1px',
                    backgroundColor: 'var(--color-border-subtle)',
                    margin: '4px 0',
                  }}
                />
              );
            }
            return (
              <button
                key={item.id}
                role="menuitem"
                disabled={item.disabled}
                onClick={() => {
                  item.onClick();
                  setIsOpen(false);
                }}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  padding: '8px 14px',
                  fontSize: '0.875rem',
                  border: 'none',
                  backgroundColor: 'transparent',
                  color: item.danger
                    ? 'var(--color-action-danger)'
                    : item.disabled
                      ? 'var(--color-text-muted)'
                      : 'var(--color-text-primary)',
                  cursor: item.disabled ? 'not-allowed' : 'pointer',
                  textAlign: 'left',
                }}
                onMouseEnter={(e) => {
                  if (!item.disabled)
                    e.currentTarget.style.backgroundColor = 'var(--color-surface-subtle)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent';
                }}
              >
                {item.icon}
                <span>{item.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};
