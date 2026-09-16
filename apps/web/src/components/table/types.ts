import React from 'react';

export type SortDirection = 'asc' | 'desc';

export interface ColumnDef<T> {
  id: string;
  header: React.ReactNode;
  accessor?: (row: T) => any;
  cell?: (row: T, index: number) => React.ReactNode;
  sortable?: boolean;
  filterable?: boolean;
  filterType?: 'text' | 'select' | 'date';
  filterOptions?: Array<{ label: string; value: string }>;
  width?: string | number;
  align?: 'left' | 'center' | 'right';
  visible?: boolean;
}

export interface SortState {
  columnId: string;
  direction: SortDirection;
}

export type TableDensity = 'compact' | 'normal' | 'comfortable';

export interface PaginationState {
  page: number;
  pageSize: number;
  totalCount: number;
}

export interface DataTableProps<T> {
  columns: ColumnDef<T>[];
  data: T[];
  keyExtractor: (row: T) => string;
  isLoading?: boolean;
  error?: Error | null;
  onRetry?: () => void;
  // Sorting
  sort?: SortState;
  onSortChange?: (sort: SortState) => void;
  // Pagination
  pagination?: PaginationState;
  onPaginationChange?: (page: number, pageSize: number) => void;
  // Selection
  selectedIds?: string[];
  onSelectionChange?: (selectedIds: string[]) => void;
  bulkActions?: React.ReactNode;
  // Density
  density?: TableDensity;
  onDensityChange?: (density: TableDensity) => void;
  // Column visibility
  columnVisibility?: Record<string, boolean>;
  onColumnVisibilityChange?: (vis: Record<string, boolean>) => void;
  // Empty message
  emptyTitle?: string;
  emptyDescription?: string;
  onRowClick?: (row: T) => void;
}
