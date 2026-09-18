import React, { useState } from 'react';
import { ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react';
import { Checkbox } from '../inputs/Checkbox';
import { Skeleton } from '../feedback/Skeleton';
import { EmptyState } from '../feedback/EmptyState';
import { ErrorState } from '../feedback/ErrorState';
import { DataTablePagination } from './DataTablePagination';
import { ColumnVisibilityMenu } from './ColumnVisibilityMenu';
import { DensityToggle } from './DensityToggle';
import { DataTableProps, ColumnDef, TableDensity } from './types';
import { useI18nText } from '../../i18n/I18nContext';

const densityPadding: Record<TableDensity, { cell: string; height: string }> = {
  compact: { cell: '4px 10px', height: '32px' },
  normal: { cell: '8px 12px', height: '44px' },
  comfortable: { cell: '14px 16px', height: '56px' },
};

export const DataTable = <T,>({
  columns,
  data,
  keyExtractor,
  isLoading = false,
  error = null,
  onRetry,
  sort,
  onSortChange,
  pagination,
  onPaginationChange,
  selectedIds,
  onSelectionChange,
  bulkActions,
  density: controlledDensity,
  onDensityChange,
  columnVisibility: controlledVisibility,
  onColumnVisibilityChange,
  emptyTitle,
  emptyDescription,
  onRowClick,
}: DataTableProps<T>) => {
  const { t, tp } = useI18nText();
  const [internalDensity, setInternalDensity] = useState<TableDensity>('normal');
  const [internalVisibility, setInternalVisibility] = useState<Record<string, boolean>>({});

  const density = controlledDensity ?? internalDensity;
  const setDensity = onDensityChange ?? setInternalDensity;

  const visibility = controlledVisibility ?? internalVisibility;
  const setVisibility = onColumnVisibilityChange ?? setInternalVisibility;

  const visibleColumns = columns.filter((col) => visibility[col.id] !== false);

  const hasSelection = Boolean(selectedIds && onSelectionChange);
  const isAllSelected =
    hasSelection &&
    data.length > 0 &&
    data.every((row) => selectedIds!.includes(keyExtractor(row)));
  const isPartiallySelected =
    hasSelection && data.some((row) => selectedIds!.includes(keyExtractor(row))) && !isAllSelected;

  const toggleSelectAll = () => {
    if (!hasSelection) return;
    if (isAllSelected) {
      onSelectionChange!([]);
    } else {
      const allRowIds = data.map(keyExtractor);
      onSelectionChange!(Array.from(new Set([...selectedIds!, ...allRowIds])));
    }
  };

  const toggleSelectRow = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!hasSelection) return;
    if (selectedIds!.includes(id)) {
      onSelectionChange!(selectedIds!.filter((item) => item !== id));
    } else {
      onSelectionChange!([...selectedIds!, id]);
    }
  };

  const handleHeaderClick = (col: ColumnDef<T>) => {
    if (!col.sortable || !onSortChange) return;
    if (sort?.columnId === col.id) {
      onSortChange({
        columnId: col.id,
        direction: sort.direction === 'asc' ? 'desc' : 'asc',
      });
    } else {
      onSortChange({ columnId: col.id, direction: 'asc' });
    }
  };

  const pad = densityPadding[density];

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: 'var(--color-surface-card)',
        borderRadius: '8px',
        border: '1px solid var(--color-border-subtle)',
        boxShadow: 'var(--shadow-card)',
        overflow: 'hidden',
        width: '100%',
      }}
    >
      {/* Table Toolbar if bulk actions or column/density controls */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 12px',
          borderBottom: '1px solid var(--color-border-subtle)',
          backgroundColor:
            selectedIds && selectedIds.length > 0 ? 'var(--color-status-info-bg)' : 'transparent',
          transition: 'background-color 150ms ease',
        }}
      >
        <div>
          {selectedIds && selectedIds.length > 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span
                style={{
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  color: 'var(--color-status-info)',
                }}
              >
                {tp('table.selected', selectedIds.length)}
              </span>
              {bulkActions}
            </div>
          ) : (
            <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
              {tp('table.displayed', data.length)}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <DensityToggle density={density} onChange={setDensity} />
          <ColumnVisibilityMenu
            columns={columns}
            visibility={visibility}
            onChange={setVisibility}
          />
        </div>
      </div>

      {/* Main Table Scroll Container */}
      <div style={{ overflowX: 'auto', width: '100%' }}>
        <table
          role="table"
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            textAlign: 'left',
            fontSize: '0.875rem',
          }}
        >
          <thead>
            <tr
              style={{
                backgroundColor: 'var(--color-surface-subtle)',
                borderBottom: '1px solid var(--color-border-subtle)',
                position: 'sticky',
                top: 0,
                zIndex: 10,
              }}
            >
              {hasSelection && (
                <th style={{ width: '40px', padding: pad.cell, textAlign: 'center' }}>
                  <Checkbox
                    checked={isAllSelected}
                    indeterminate={isPartiallySelected}
                    onChange={toggleSelectAll}
                    aria-label={t('table.select_all')}
                  />
                </th>
              )}
              {visibleColumns.map((col) => {
                const isSorted = sort?.columnId === col.id;
                return (
                  <th
                    key={col.id}
                    aria-sort={
                      col.sortable
                        ? isSorted
                          ? sort.direction === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                        : undefined
                    }
                    style={{
                      padding: pad.cell,
                      width: col.width,
                      textAlign: col.align || 'left',
                      fontWeight: 600,
                      color: isSorted
                        ? 'var(--color-action-primary)'
                        : 'var(--color-text-secondary)',
                      userSelect: 'none',
                    }}
                  >
                    {col.sortable ? (
                      <button
                        type="button"
                        onClick={() => handleHeaderClick(col)}
                        aria-label={t('table.sort_by', { label: String(col.header) })}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px',
                          justifyContent:
                            col.align === 'right'
                              ? 'flex-end'
                              : col.align === 'center'
                                ? 'center'
                                : 'flex-start',
                          background: 'none',
                          border: 'none',
                          padding: 0,
                          cursor: 'pointer',
                          fontWeight: 600,
                          color: 'inherit',
                          fontSize: 'inherit',
                          width: '100%',
                        }}
                      >
                        <span>{col.header}</span>
                        <span>
                          {isSorted ? (
                            sort.direction === 'asc' ? (
                              <ArrowUp size={14} />
                            ) : (
                              <ArrowDown size={14} />
                            )
                          ) : (
                            <ArrowUpDown size={14} style={{ opacity: 0.4 }} />
                          )}
                        </span>
                      </button>
                    ) : (
                      <div
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px',
                          justifyContent:
                            col.align === 'right'
                              ? 'flex-end'
                              : col.align === 'center'
                                ? 'center'
                                : 'flex-start',
                        }}
                      >
                        <span>{col.header}</span>
                      </div>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {error ? (
              <tr>
                <td colSpan={visibleColumns.length + (hasSelection ? 1 : 0)}>
                  <ErrorState error={error} onRetry={onRetry} />
                </td>
              </tr>
            ) : isLoading ? (
              Array.from({ length: 5 }).map((_, rIdx) => (
                <tr
                  key={`skel-${rIdx}`}
                  style={{ borderBottom: '1px solid var(--color-border-subtle)' }}
                >
                  {hasSelection && (
                    <td style={{ padding: pad.cell, textAlign: 'center' }}>
                      <Skeleton width="16px" height="16px" />
                    </td>
                  )}
                  {visibleColumns.map((c) => (
                    <td key={c.id} style={{ padding: pad.cell }}>
                      <Skeleton width="75%" height="14px" />
                    </td>
                  ))}
                </tr>
              ))
            ) : data.length === 0 ? (
              <tr>
                <td colSpan={visibleColumns.length + (hasSelection ? 1 : 0)}>
                  <EmptyState
                    title={emptyTitle ?? t('table.empty_title')}
                    description={emptyDescription ?? t('table.empty_body')}
                  />
                </td>
              </tr>
            ) : (
              data.map((row, index) => {
                const rowKey = keyExtractor(row);
                const isSelected = selectedIds?.includes(rowKey);

                return (
                  <tr
                    key={rowKey}
                    onClick={() => onRowClick?.(row)}
                    style={{
                      borderBottom: '1px solid var(--color-border-subtle)',
                      backgroundColor: isSelected ? 'var(--color-surface-subtle)' : 'transparent',
                      cursor: onRowClick ? 'pointer' : 'default',
                      transition: 'background-color 100ms ease',
                    }}
                    onMouseEnter={(e) => {
                      if (!isSelected)
                        e.currentTarget.style.backgroundColor = 'var(--color-surface-subtle)';
                    }}
                    onMouseLeave={(e) => {
                      if (!isSelected) e.currentTarget.style.backgroundColor = 'transparent';
                    }}
                  >
                    {hasSelection && (
                      <td
                        style={{ width: '40px', padding: pad.cell, textAlign: 'center' }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Checkbox
                          checked={isSelected}
                          onChange={(e) => toggleSelectRow(rowKey, e as any)}
                          aria-label={t('table.select_row', { row: index + 1 })}
                        />
                      </td>
                    )}
                    {visibleColumns.map((col) => {
                      let cellContent: React.ReactNode;
                      if (col.cell) {
                        cellContent = col.cell(row, index);
                      } else if (col.accessor) {
                        cellContent = String(col.accessor(row) ?? '');
                      } else {
                        cellContent = String((row as any)[col.id] ?? '');
                      }

                      return (
                        <td
                          key={col.id}
                          style={{
                            padding: pad.cell,
                            textAlign: col.align || 'left',
                            color: 'var(--color-text-primary)',
                          }}
                        >
                          {cellContent}
                        </td>
                      );
                    })}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      {pagination && onPaginationChange && (
        <DataTablePagination pagination={pagination} onPageChange={onPaginationChange} />
      )}
    </div>
  );
};
