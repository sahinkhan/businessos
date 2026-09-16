import React, { useState } from 'react';
import { Card } from '../components/structure/Card';
import { Tabs } from '../components/structure/Tabs';
import { ListPageShell } from '../layouts/ListPageShell';
import { DetailPageShell } from '../layouts/DetailPageShell';
import { WizardPageShell } from '../layouts/WizardPageShell';
import { Button } from '../components/actions/Button';
import { useToast } from '../components/feedback/Toast';
import { Plus, Download, Edit } from 'lucide-react';

export const LayoutsDemoPage: React.FC = () => {
  const [wizardStep, setWizardStep] = useState(0);
  const toast = useToast();

  const listTab = (
    <ListPageShell
      title="Master Procurement Orders"
      description="All purchase orders authorized across current operating sites."
      primaryAction={
        <Button variant="primary" leftIcon={<Plus size={16} />}>
          Create Order
        </Button>
      }
      secondaryActions={
        <Button variant="outline" leftIcon={<Download size={16} />}>
          Export
        </Button>
      }
    >
      <Card>
        <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>
          ListPageShell enforces consistent header spacing, action bar placement, search/filter
          slots, and data table alignment across all business modules.
        </p>
      </Card>
    </ListPageShell>
  );

  const detailTab = (
    <DetailPageShell
      title="Order PO-2026-9042"
      subtitle="Operating Site SEA-01 • Created Sep 14, 2026 by Administrator"
      statusBadge={
        <span
          style={{
            padding: '2px 8px',
            borderRadius: '9999px',
            backgroundColor: 'var(--color-status-success-bg)',
            color: 'var(--color-status-success)',
            fontSize: '0.75rem',
            fontWeight: 600,
          }}
        >
          APPROVED
        </span>
      }
      actions={
        <div style={{ display: 'flex', gap: '8px' }}>
          <Button variant="outline" size="sm" leftIcon={<Edit size={14} />}>
            Edit Record
          </Button>
          <Button variant="primary" size="sm">
            Approve Batch
          </Button>
        </div>
      }
      auditFooter="Immutable ledger record ID: tx_99214 • SHA-256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    >
      <Card title="Order Specifications">
        <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>
          DetailPageShell coordinates record titles, breadcrumbs, status tags, action buttons, tab
          navigation, and audit trail footers.
        </p>
      </Card>
    </DetailPageShell>
  );

  const wizardTab = (
    <WizardPageShell
      title="Operating Site Provisioning Wizard"
      steps={[
        { id: 'step_1', title: 'Legal Entity' },
        { id: 'step_2', title: 'Site Parameters' },
        { id: 'step_3', title: 'Policy Grants' },
      ]}
      currentStepIndex={wizardStep}
      onNext={() => setWizardStep((prev) => Math.min(2, prev + 1))}
      onPrev={() => setWizardStep((prev) => Math.max(0, prev - 1))}
      onFinish={() => {
        toast.success('Wizard Complete', 'Site provisioning profile finalized.');
        setWizardStep(0);
      }}
    >
      <Card>
        {wizardStep === 0 && (
          <div>
            <h4 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '8px' }}>
              Step 1: Select Legal Entity
            </h4>
            <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>
              Select the corporate entity owning the target operating facility.
            </p>
          </div>
        )}
        {wizardStep === 1 && (
          <div>
            <h4 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '8px' }}>
              Step 2: Operating Site Parameters
            </h4>
            <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>
              Configure base currency, timezone, facility code, and physical coordinates.
            </p>
          </div>
        )}
        {wizardStep === 2 && (
          <div>
            <h4 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '8px' }}>
              Step 3: Initial Policy Grants
            </h4>
            <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>
              Assign local manager roles and fiscal approval limits.
            </p>
          </div>
        )}
      </Card>
    </WizardPageShell>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          Standard Page Layout Archetypes
        </h1>
        <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
          Tested layout shells: ListPageShell, DetailPageShell, FormPageShell, and WizardPageShell.
        </p>
      </div>

      <Card>
        <Tabs
          items={[
            { id: 'list', label: 'List Page Shell', content: listTab },
            { id: 'detail', label: 'Detail Page Shell', content: detailTab },
            { id: 'wizard', label: 'Wizard Page Shell', content: wizardTab },
          ]}
        />
      </Card>
    </div>
  );
};
