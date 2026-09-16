import React from 'react';
import { Card } from '../components/structure/Card';

export interface SettingsCategory {
  id: string;
  label: string;
  icon?: React.ReactNode;
}

export interface SettingsPageShellProps {
  title: string;
  categories: SettingsCategory[];
  activeCategoryId: string;
  onSelectCategory: (id: string) => void;
  children: React.ReactNode;
}

export const SettingsPageShell: React.FC<SettingsPageShellProps> = ({
  title,
  categories,
  activeCategoryId,
  onSelectCategory,
  children,
}) => {
  return (
    <div>
      <h1
        style={{
          fontSize: '1.5rem',
          fontWeight: 700,
          color: 'var(--color-text-primary)',
          marginBottom: '20px',
        }}
      >
        {title}
      </h1>
      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: '24px' }}>
        <Card padding="sm">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {categories.map((cat) => (
              <button
                key={cat.id}
                type="button"
                onClick={() => onSelectCategory(cat.id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  border: 'none',
                  textAlign: 'left',
                  cursor: 'pointer',
                  fontSize: '0.875rem',
                  fontWeight: cat.id === activeCategoryId ? 600 : 500,
                  backgroundColor:
                    cat.id === activeCategoryId ? 'var(--color-surface-subtle)' : 'transparent',
                  color:
                    cat.id === activeCategoryId
                      ? 'var(--color-action-primary)'
                      : 'var(--color-text-secondary)',
                }}
              >
                {cat.icon}
                <span>{cat.label}</span>
              </button>
            ))}
          </div>
        </Card>
        <div>{children}</div>
      </div>
    </div>
  );
};
