import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { DataTable } from '../../src/components/table/DataTable';
import { ColumnDef } from '../../src/components/table/types';

interface TestItem {
  id: string;
  name: string;
  code: string;
}

const columns: ColumnDef<TestItem>[] = [
  { id: 'code', header: 'Code', accessor: (r) => r.code, sortable: true },
  { id: 'name', header: 'Name', accessor: (r) => r.name, sortable: true },
];

const mockData: TestItem[] = [
  { id: '1', code: 'A01', name: 'Item Alpha' },
  { id: '2', code: 'B02', name: 'Item Beta' },
];

describe('DataTable Primitive', () => {
  it('renders table headers and rows correctly', () => {
    render(<DataTable columns={columns} data={mockData} keyExtractor={(r) => r.id} />);

    expect(screen.getByText('Code')).toBeInTheDocument();
    expect(screen.getByText('Name')).toBeInTheDocument();
    expect(screen.getByText('Item Alpha')).toBeInTheDocument();
    expect(screen.getByText('Item Beta')).toBeInTheDocument();
  });

  it('triggers sorting callback on header click', () => {
    const handleSort = vi.fn();
    render(
      <DataTable
        columns={columns}
        data={mockData}
        keyExtractor={(r) => r.id}
        sort={{ columnId: 'code', direction: 'asc' }}
        onSortChange={handleSort}
      />
    );

    const sortButton = screen.getByRole('button', { name: /Sort by Code/i });
    fireEvent.click(sortButton);

    expect(handleSort).toHaveBeenCalledWith({
      columnId: 'code',
      direction: 'desc',
    });
  });

  it('supports row selection and bulk actions', () => {
    const handleSelection = vi.fn();
    render(
      <DataTable
        columns={columns}
        data={mockData}
        keyExtractor={(r) => r.id}
        selectedIds={['1']}
        onSelectionChange={handleSelection}
      />
    );

    const selectAllCheckbox = screen.getByRole('checkbox', { name: /Select all rows/i });
    expect(selectAllCheckbox).toBeInTheDocument();

    const rowCheckboxes = screen.getAllByRole('checkbox', { name: /Select row/i });
    expect(rowCheckboxes[0]).toBeChecked();
    expect(rowCheckboxes[1]).not.toBeChecked();

    fireEvent.click(rowCheckboxes[1]);
    expect(handleSelection).toHaveBeenCalledWith(['1', '2']);
  });
});
