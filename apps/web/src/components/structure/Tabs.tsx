import React, { useState } from 'react';

export interface TabItem {
  id: string;
  label: React.ReactNode;
  icon?: React.ReactNode;
  badge?: React.ReactNode;
  disabled?: boolean;
  content: React.ReactNode;
}

export interface TabsProps {
  items: TabItem[];
  activeTab?: string;
  onTabChange?: (tabId: string) => void;
  variant?: 'line' | 'enclosed';
}

export const Tabs: React.FC<TabsProps> = ({
  items,
  activeTab: controlledActiveTab,
  onTabChange,
  variant = 'line',
}) => {
  const [internalActiveTab, setInternalActiveTab] = useState<string>(items[0]?.id || '');
  const activeId = controlledActiveTab !== undefined ? controlledActiveTab : internalActiveTab;

  const handleSelect = (id: string) => {
    if (controlledActiveTab === undefined) {
      setInternalActiveTab(id);
    }
    onTabChange?.(id);
  };

  const activeItem = items.find((item) => item.id === activeId) || items[0];

  return (
    <div>
      <div
        role="tablist"
        style={{
          display: 'flex',
          gap: variant === 'enclosed' ? '4px' : '16px',
          borderBottom: '1px solid var(--color-border-subtle)',
          overflowX: 'auto',
        }}
      >
        {items.map((tab) => {
          const isActive = tab.id === activeId;
          return (
            <button
              key={tab.id}
              role="tab"
              id={`tab-${tab.id}`}
              aria-controls={`tabpanel-${tab.id}`}
              aria-selected={isActive}
              disabled={tab.disabled}
              onClick={() => handleSelect(tab.id)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                padding: '10px 14px',
                fontSize: '0.875rem',
                fontWeight: isActive ? 600 : 500,
                color: isActive ? 'var(--color-action-primary)' : 'var(--color-text-secondary)',
                backgroundColor:
                  variant === 'enclosed' && isActive
                    ? 'var(--color-surface-subtle)'
                    : 'transparent',
                border: 'none',
                borderBottom:
                  variant === 'line'
                    ? isActive
                      ? '2px solid var(--color-action-primary)'
                      : '2px solid transparent'
                    : 'none',
                borderTopLeftRadius: variant === 'enclosed' ? '6px' : 0,
                borderTopRightRadius: variant === 'enclosed' ? '6px' : 0,
                cursor: tab.disabled ? 'not-allowed' : 'pointer',
                opacity: tab.disabled ? 0.5 : 1,
                whiteSpace: 'nowrap',
              }}
            >
              {tab.icon}
              <span>{tab.label}</span>
              {tab.badge && (
                <span
                  style={{
                    backgroundColor: 'var(--color-surface-subtle)',
                    padding: '2px 6px',
                    borderRadius: '9999px',
                    fontSize: '0.75rem',
                  }}
                >
                  {tab.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>
      <div
        role="tabpanel"
        id={`tabpanel-${activeItem?.id}`}
        aria-labelledby={`tab-${activeItem?.id}`}
        style={{ paddingTop: '16px' }}
      >
        {activeItem?.content}
      </div>
    </div>
  );
};
