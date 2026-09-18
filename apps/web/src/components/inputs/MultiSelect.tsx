import React, { useState, useRef, useEffect } from 'react';
import { X, ChevronDown } from 'lucide-react';
import { SelectOption } from './Select';
import { useI18nText } from '../../i18n/I18nContext';

export interface MultiSelectProps {
  options: SelectOption[];
  value: string[];
  onChange: (selected: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  error?: boolean;
  'aria-label'?: string;
}

export const MultiSelect: React.FC<MultiSelectProps> = ({
  options,
  value,
  onChange,
  placeholder,
  disabled,
  error,
  'aria-label': ariaLabel,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const { t } = useI18nText();
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

  const toggleOption = (val: string) => {
    if (value.includes(val)) {
      onChange(value.filter((v) => v !== val));
    } else {
      onChange([...value, val]);
    }
  };

  const removeValue = (val: string, e: React.MouseEvent) => {
    e.stopPropagation();
    onChange(value.filter((v) => v !== val));
  };

  return (
    <div ref={containerRef} style={{ position: 'relative', width: '100%' }}>
      <div
        role="combobox"
        aria-expanded={isOpen}
        aria-label={ariaLabel}
        tabIndex={disabled ? -1 : 0}
        onClick={() => !disabled && setIsOpen(!isOpen)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            if (!disabled) setIsOpen(!isOpen);
          }
        }}
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: '4px',
          minHeight: '36px',
          padding: '4px 8px',
          borderRadius: '6px',
          backgroundColor: disabled ? 'var(--color-surface-subtle)' : 'var(--color-surface-card)',
          border: `1px solid ${error ? 'var(--color-status-danger)' : 'var(--color-border-default)'}`,
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.6 : 1,
        }}
      >
        {value.length === 0 && (
          <span style={{ color: 'var(--color-text-muted)', fontSize: '0.875rem' }}>
            {placeholder ?? t('controls.select_options')}
          </span>
        )}
        {value.map((v) => {
          const opt = options.find((o) => o.value === v);
          return (
            <span
              key={v}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '2px 6px',
                backgroundColor: 'var(--color-surface-subtle)',
                borderRadius: '4px',
                fontSize: '0.75rem',
                fontWeight: 500,
              }}
            >
              {opt?.label || v}
              {!disabled && (
                <button
                  type="button"
                  onClick={(e) => removeValue(v, e)}
                  aria-label={t('controls.remove_option', { label: opt?.label || v })}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                >
                  <X size={12} />
                </button>
              )}
            </span>
          );
        })}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center' }}>
          <ChevronDown size={16} color="var(--color-text-muted)" />
        </div>
      </div>

      {isOpen && (
        <div
          role="listbox"
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            marginTop: '4px',
            maxHeight: '200px',
            overflowY: 'auto',
            backgroundColor: 'var(--color-surface-card)',
            border: '1px solid var(--color-border-subtle)',
            borderRadius: '6px',
            boxShadow: 'var(--shadow-dropdown)',
            zIndex: 1000,
            padding: '4px',
          }}
        >
          {options.map((opt) => {
            const isSelected = value.includes(opt.value);
            return (
              <div
                key={opt.value}
                role="option"
                aria-selected={isSelected}
                onClick={() => toggleOption(opt.value)}
                style={{
                  padding: '6px 10px',
                  borderRadius: '4px',
                  fontSize: '0.875rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  backgroundColor: isSelected ? 'var(--color-surface-subtle)' : 'transparent',
                  color: isSelected ? 'var(--color-action-primary)' : 'var(--color-text-primary)',
                  cursor: 'pointer',
                  fontWeight: isSelected ? 600 : 400,
                }}
              >
                <span>{opt.label}</span>
                {isSelected && <span style={{ fontSize: '0.75rem' }}>✓</span>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
