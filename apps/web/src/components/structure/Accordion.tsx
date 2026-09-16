import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';

export interface AccordionItemData {
  id: string;
  title: React.ReactNode;
  content: React.ReactNode;
  disabled?: boolean;
}

export interface AccordionProps {
  items: AccordionItemData[];
  allowMultiple?: boolean;
  defaultOpen?: string[];
}

export const Accordion: React.FC<AccordionProps> = ({
  items,
  allowMultiple = false,
  defaultOpen = [],
}) => {
  const [openIds, setOpenIds] = useState<string[]>(defaultOpen);

  const toggle = (id: string) => {
    if (openIds.includes(id)) {
      setOpenIds(openIds.filter((item) => item !== id));
    } else {
      setOpenIds(allowMultiple ? [...openIds, id] : [id]);
    }
  };

  return (
    <div
      style={{
        border: '1px solid var(--color-border-subtle)',
        borderRadius: '6px',
        overflow: 'hidden',
      }}
    >
      {items.map((item, index) => {
        const isOpen = openIds.includes(item.id);
        const isLast = index === items.length - 1;

        return (
          <div
            key={item.id}
            style={{ borderBottom: isLast ? 'none' : '1px solid var(--color-border-subtle)' }}
          >
            <button
              type="button"
              disabled={item.disabled}
              onClick={() => toggle(item.id)}
              aria-expanded={isOpen}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '12px 16px',
                backgroundColor: 'var(--color-surface-card)',
                border: 'none',
                textAlign: 'left',
                cursor: item.disabled ? 'not-allowed' : 'pointer',
                opacity: item.disabled ? 0.6 : 1,
                fontWeight: 600,
                fontSize: '0.875rem',
                color: 'var(--color-text-primary)',
              }}
            >
              <span>{item.title}</span>
              <ChevronDown
                size={16}
                style={{
                  transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                  transition: 'transform 200ms ease',
                  color: 'var(--color-text-muted)',
                }}
              />
            </button>
            {isOpen && (
              <div
                style={{
                  padding: '12px 16px',
                  backgroundColor: 'var(--color-surface-subtle)',
                  fontSize: '0.875rem',
                  color: 'var(--color-text-secondary)',
                  borderTop: '1px solid var(--color-border-subtle)',
                }}
              >
                {item.content}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};
