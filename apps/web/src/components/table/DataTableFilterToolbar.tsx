import React from 'react';
import { X } from 'lucide-react';
import { SearchInput } from '../inputs/SearchInput';
import { Button } from '../actions/Button';
import { useI18nText } from '../../i18n/I18nContext';

export interface FilterChip {
  id: string;
  label: string;
  value: string;
}

export interface DataTableFilterToolbarProps {
  searchQuery: string;
  onSearchChange: (query: string) => void;
  activeFilters: FilterChip[];
  onRemoveFilter: (id: string) => void;
  onClearAllFilters: () => void;
  children?: React.ReactNode;
}

export const DataTableFilterToolbar: React.FC<DataTableFilterToolbarProps> = ({
  searchQuery,
  onSearchChange,
  activeFilters,
  onRemoveFilter,
  onClearAllFilters,
  children,
}) => {
  const { t } = useI18nText();
  return (
    <div style={{ marginBottom: '12px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
        <div style={{ maxWidth: '280px', flex: 1 }}>
          <SearchInput
            value={searchQuery}
            onSearchChange={onSearchChange}
            placeholder={t('table.filter_records')}
          />
        </div>
        {children}
      </div>
      {activeFilters.length > 0 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            flexWrap: 'wrap',
            marginTop: '8px',
          }}
        >
          <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
            {t('table.active_filters')}
          </span>
          {activeFilters.map((chip) => (
            <span
              key={chip.id}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '2px 8px',
                backgroundColor: 'var(--color-surface-subtle)',
                border: '1px solid var(--color-border-subtle)',
                borderRadius: '9999px',
                fontSize: '0.75rem',
                color: 'var(--color-text-primary)',
              }}
            >
              <span>
                {chip.label}: <strong>{chip.value}</strong>
              </span>
              <button
                type="button"
                onClick={() => onRemoveFilter(chip.id)}
                aria-label={t('table.remove_filter', { label: chip.label })}
                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
              >
                <X size={12} />
              </button>
            </span>
          ))}
          <Button
            variant="ghost"
            size="sm"
            onClick={onClearAllFilters}
            style={{ padding: '2px 6px', fontSize: '0.75rem' }}
          >
            {t('common.clear_all')}
          </Button>
        </div>
      )}
    </div>
  );
};
