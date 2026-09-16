import React, { useState, useMemo } from 'react';
import { DataTable } from '../components/table/DataTable';
import { ColumnDef, SortState } from '../components/table/types';
import { DataTableFilterToolbar } from '../components/table/DataTableFilterToolbar';
import { Button } from '../components/actions/Button';
import { useToast } from '../components/feedback/Toast';
import { Download, Trash2 } from 'lucide-react';

interface MockRecord {
  id: string;
  code: string;
  name: string;
  category: string;
  amount: number;
  status: 'active' | 'pending' | 'archived';
  updatedAt: string;
}

const RAW_DATA: MockRecord[] = [
  {
    id: 'rec_01',
    code: 'DOC-1001',
    name: 'Global Supply Agreement',
    category: 'Legal',
    amount: 154000.0,
    status: 'active',
    updatedAt: '2026-09-14',
  },
  {
    id: 'rec_02',
    code: 'DOC-1002',
    name: 'Logistics Facility Lease',
    category: 'Operations',
    amount: 82500.5,
    status: 'active',
    updatedAt: '2026-09-12',
  },
  {
    id: 'rec_03',
    code: 'DOC-1003',
    name: 'Software Enterprise Licensing',
    category: 'Technology',
    amount: 49200.0,
    status: 'pending',
    updatedAt: '2026-09-15',
  },
  {
    id: 'rec_04',
    code: 'DOC-1004',
    name: 'Fleet Maintenance Contract',
    category: 'Operations',
    amount: 19800.0,
    status: 'active',
    updatedAt: '2026-09-10',
  },
  {
    id: 'rec_05',
    code: 'DOC-1005',
    name: 'Audit & Tax Advisory',
    category: 'Finance',
    amount: 65000.0,
    status: 'archived',
    updatedAt: '2026-09-08',
  },
  {
    id: 'rec_06',
    code: 'DOC-1006',
    name: 'Cloud Infrastructure Reserve',
    category: 'Technology',
    amount: 120000.0,
    status: 'active',
    updatedAt: '2026-09-16',
  },
  {
    id: 'rec_07',
    code: 'DOC-1007',
    name: 'Industrial Security Patrol',
    category: 'Operations',
    amount: 14200.0,
    status: 'pending',
    updatedAt: '2026-09-11',
  },
];

export const DataTableDemoPage: React.FC = () => {
  const [data] = useState<MockRecord[]>(RAW_DATA);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [sort, setSort] = useState<SortState>({ columnId: 'code', direction: 'asc' });
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const toast = useToast();

  const columns: ColumnDef<MockRecord>[] = [
    {
      id: 'code',
      header: 'Document ID',
      accessor: (r) => r.code,
      sortable: true,
      width: '140px',
    },
    {
      id: 'name',
      header: 'Title / Description',
      accessor: (r) => r.name,
      sortable: true,
    },
    {
      id: 'category',
      header: 'Category',
      accessor: (r) => r.category,
      sortable: true,
      width: '130px',
    },
    {
      id: 'amount',
      header: 'Value (USD)',
      accessor: (r) => r.amount,
      sortable: true,
      align: 'right',
      cell: (r) => `$${r.amount.toLocaleString('en-US', { minimumFractionDigits: 2 })}`,
      width: '150px',
    },
    {
      id: 'status',
      header: 'Status',
      accessor: (r) => r.status,
      sortable: true,
      width: '120px',
      cell: (r) => {
        const bg =
          r.status === 'active'
            ? 'var(--color-status-success-bg)'
            : r.status === 'pending'
              ? 'var(--color-status-warning-bg)'
              : 'var(--color-surface-subtle)';
        const text =
          r.status === 'active'
            ? 'var(--color-status-success)'
            : r.status === 'pending'
              ? 'var(--color-status-warning)'
              : 'var(--color-text-muted)';
        return (
          <span
            style={{
              padding: '2px 8px',
              borderRadius: '9999px',
              backgroundColor: bg,
              color: text,
              fontSize: '0.75rem',
              fontWeight: 600,
              textTransform: 'capitalize',
            }}
          >
            {r.status}
          </span>
        );
      },
    },
    {
      id: 'updatedAt',
      header: 'Last Modified',
      accessor: (r) => r.updatedAt,
      sortable: true,
      width: '130px',
    },
  ];

  // Filtering & Sorting
  const filteredAndSortedData = useMemo(() => {
    let result = [...data];

    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (r) =>
          r.code.toLowerCase().includes(q) ||
          r.name.toLowerCase().includes(q) ||
          r.category.toLowerCase().includes(q)
      );
    }

    if (statusFilter !== 'all') {
      result = result.filter((r) => r.status === statusFilter);
    }

    result.sort((a, b) => {
      const valA = (a as any)[sort.columnId];
      const valB = (b as any)[sort.columnId];
      if (valA < valB) return sort.direction === 'asc' ? -1 : 1;
      if (valA > valB) return sort.direction === 'asc' ? 1 : -1;
      return 0;
    });

    return result;
  }, [data, searchQuery, statusFilter, sort]);

  const pagedData = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filteredAndSortedData.slice(start, start + pageSize);
  }, [filteredAndSortedData, page, pageSize]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          Enterprise DataTable Demonstration
        </h1>
        <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
          High-performance table foundation with server-ready pagination, multi-column sorting,
          selection, and density control.
        </p>
      </div>

      <DataTableFilterToolbar
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        activeFilters={
          statusFilter !== 'all' ? [{ id: 'status', label: 'Status', value: statusFilter }] : []
        }
        onRemoveFilter={() => setStatusFilter('all')}
        onClearAllFilters={() => {
          setSearchQuery('');
          setStatusFilter('all');
        }}
      >
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Filter by status"
          style={{
            height: '36px',
            padding: '0 10px',
            borderRadius: '6px',
            border: '1px solid var(--color-border-default)',
            backgroundColor: 'var(--color-surface-card)',
            color: 'var(--color-text-primary)',
            fontSize: '0.8125rem',
          }}
        >
          <option value="all">All Statuses</option>
          <option value="active">Active</option>
          <option value="pending">Pending</option>
          <option value="archived">Archived</option>
        </select>
      </DataTableFilterToolbar>

      <DataTable
        columns={columns}
        data={pagedData}
        keyExtractor={(r) => r.id}
        sort={sort}
        onSortChange={setSort}
        pagination={{
          page,
          pageSize,
          totalCount: filteredAndSortedData.length,
        }}
        onPaginationChange={(newPage, newSize) => {
          setPage(newPage);
          setPageSize(newSize);
        }}
        selectedIds={selectedIds}
        onSelectionChange={setSelectedIds}
        bulkActions={
          <div style={{ display: 'flex', gap: '6px' }}>
            <Button
              variant="outline"
              size="sm"
              leftIcon={<Download size={14} />}
              onClick={() =>
                toast.success('Export Batch', `Exported ${selectedIds.length} records`)
              }
            >
              Export Selected
            </Button>
            <Button
              variant="danger"
              size="sm"
              leftIcon={<Trash2 size={14} />}
              onClick={() => {
                toast.warning('Delete Action', `Marked ${selectedIds.length} records for deletion`);
                setSelectedIds([]);
              }}
            >
              Delete Selected
            </Button>
          </div>
        }
      />
    </div>
  );
};
