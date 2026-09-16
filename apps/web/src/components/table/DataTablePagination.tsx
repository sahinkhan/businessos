import React from 'react';
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';
import { IconButton } from '../actions/IconButton';
import { PaginationState } from './types';

export interface DataTablePaginationProps {
  pagination: PaginationState;
  onPageChange: (page: number, pageSize: number) => void;
  pageSizeOptions?: number[];
}

export const DataTablePagination: React.FC<DataTablePaginationProps> = ({
  pagination,
  onPageChange,
  pageSizeOptions = [10, 25, 50, 100],
}) => {
  const { page, pageSize, totalCount } = pagination;
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const startItem = totalCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const endItem = Math.min(page * pageSize, totalCount);

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px 16px',
        borderTop: '1px solid var(--color-border-subtle)',
        fontSize: '0.8125rem',
        color: 'var(--color-text-secondary)',
        flexWrap: 'wrap',
        gap: '12px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span>Rows per page:</span>
        <select
          value={pageSize}
          onChange={(e) => onPageChange(1, Number(e.target.value))}
          style={{
            padding: '2px 6px',
            borderRadius: '4px',
            border: '1px solid var(--color-border-default)',
            backgroundColor: 'var(--color-surface-card)',
            color: 'var(--color-text-primary)',
            fontSize: '0.8125rem',
          }}
        >
          {pageSizeOptions.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
        <span>
          {startItem}-{endItem} of {totalCount}
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        <IconButton
          icon={<ChevronsLeft size={16} />}
          aria-label="First page"
          size="sm"
          variant="ghost"
          disabled={page <= 1}
          onClick={() => onPageChange(1, pageSize)}
        />
        <IconButton
          icon={<ChevronLeft size={16} />}
          aria-label="Previous page"
          size="sm"
          variant="ghost"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1, pageSize)}
        />
        <span style={{ margin: '0 8px' }}>
          Page {page} of {totalPages}
        </span>
        <IconButton
          icon={<ChevronRight size={16} />}
          aria-label="Next page"
          size="sm"
          variant="ghost"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1, pageSize)}
        />
        <IconButton
          icon={<ChevronsRight size={16} />}
          aria-label="Last page"
          size="sm"
          variant="ghost"
          disabled={page >= totalPages}
          onClick={() => onPageChange(totalPages, pageSize)}
        />
      </div>
    </div>
  );
};
