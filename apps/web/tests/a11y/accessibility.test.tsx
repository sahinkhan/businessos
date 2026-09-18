import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import axe from 'axe-core';
import { Button } from '../../src/components/actions/Button';
import { FormField } from '../../src/components/form/FormField';
import { TextInput } from '../../src/components/inputs/TextInput';
import { Alert } from '../../src/components/feedback/Alert';
import { Modal } from '../../src/components/overlays/Modal';
import { DataTable } from '../../src/components/table/DataTable';
import { ColumnDef } from '../../src/components/table/types';
import { Card } from '../../src/components/structure/Card';

describe('Automated WCAG AA Accessibility Audits', () => {
  it('Button primitive satisfies axe-core accessibility standards', async () => {
    const { container } = render(<Button variant="primary">Accessible Action</Button>);
    const results = await axe.run(container);
    expect(results.violations).toEqual([]);
  });

  it('FormField primitive with label and input satisfies axe-core', async () => {
    const { container } = render(
      <FormField id="acc_name" label="Full Name" helpText="Legal naming" required>
        <TextInput id="acc_name" />
      </FormField>
    );
    const results = await axe.run(container);
    expect(results.violations).toEqual([]);
  });

  it('Alert feedback primitive satisfies axe-core standards', async () => {
    const { container } = render(
      <Alert severity="warning" title="Audit Required">
        Review required documentation before proceeding.
      </Alert>
    );
    const results = await axe.run(container);
    expect(results.violations).toEqual([]);
  });

  it('Card structure primitive satisfies axe-core standards', async () => {
    const { container } = render(
      <Card title="Operational Metric">
        <p>Summary of enterprise activity.</p>
      </Card>
    );
    const results = await axe.run(container);
    expect(results.violations).toEqual([]);
  });

  it('DataTable satisfies axe-core table accessibility standards', async () => {
    interface AuditRow {
      id: string;
      code: string;
      status: string;
    }
    const cols: ColumnDef<AuditRow>[] = [
      { id: 'code', header: 'Reference Code', accessor: (r) => r.code },
      { id: 'status', header: 'Operational Status', accessor: (r) => r.status },
    ];
    const data: AuditRow[] = [
      { id: '1', code: 'REF-001', status: 'Approved' },
      { id: '2', code: 'REF-002', status: 'Pending' },
    ];

    const { container } = render(
      <DataTable columns={cols} data={data} keyExtractor={(r) => r.id} />
    );
    const results = await axe.run(container);
    expect(results.violations).toEqual([]);
  });

  it('Modal dialog satisfies axe-core accessibility standards', async () => {
    const { baseElement } = render(
      <Modal
        isOpen={true}
        onClose={() => {}}
        title="Accessibility Audit Dialog"
        footer={<Button variant="secondary">Close</Button>}
      >
        <p>Accessible modal dialog content adhering to WAI-ARIA standards.</p>
      </Modal>
    );
    const results = await axe.run(baseElement);
    expect(results.violations).toEqual([]);
  });
});
