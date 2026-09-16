import { useState, useRef, useEffect } from 'react';
import { Columns } from 'lucide-react';
import { Button } from '../actions/Button';
import { Checkbox } from '../inputs/Checkbox';
import { ColumnDef } from './types';

export interface ColumnVisibilityMenuProps<T> {
  columns: ColumnDef<T>[];
  visibility: Record<string, boolean>;
  onChange: (vis: Record<string, boolean>) => void;
}

export const ColumnVisibilityMenu = <T,>({
  columns,
  visibility,
  onChange,
}: ColumnVisibilityMenuProps<T>) => {
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setIsOpen(false);
    };
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, []);

  const toggleColumn = (colId: string) => {
    const current = visibility[colId] ?? true;
    onChange({ ...visibility, [colId]: !current });
  };

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <Button
        variant="outline"
        size="sm"
        leftIcon={<Columns size={14} />}
        onClick={() => setIsOpen(!isOpen)}
        aria-label="Columns"
      >
        Columns
      </Button>
      {isOpen && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            right: 0,
            marginTop: '4px',
            backgroundColor: 'var(--color-surface-card)',
            border: '1px solid var(--color-border-subtle)',
            borderRadius: '6px',
            boxShadow: 'var(--shadow-dropdown)',
            zIndex: 1000,
            minWidth: '180px',
            padding: '8px 12px',
          }}
        >
          <div
            style={{
              fontSize: '0.75rem',
              fontWeight: 600,
              color: 'var(--color-text-muted)',
              marginBottom: '6px',
            }}
          >
            TOGGLE COLUMNS
          </div>
          {columns.map((col) => {
            const isVisible = visibility[col.id] ?? true;
            return (
              <div key={col.id} style={{ margin: '4px 0' }}>
                <Checkbox
                  label={typeof col.header === 'string' ? col.header : col.id}
                  checked={isVisible}
                  onChange={() => toggleColumn(col.id)}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
