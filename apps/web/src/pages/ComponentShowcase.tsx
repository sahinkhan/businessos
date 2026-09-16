import React, { useState } from 'react';
import { Card } from '../components/structure/Card';
import { Button } from '../components/actions/Button';
import { IconButton } from '../components/actions/IconButton';
import { SplitButton } from '../components/actions/SplitButton';
import { Tabs } from '../components/structure/Tabs';
import { Modal } from '../components/overlays/Modal';
import { Drawer } from '../components/overlays/Drawer';
import { Tooltip } from '../components/overlays/Tooltip';
import { Alert } from '../components/feedback/Alert';
import { Progress } from '../components/feedback/Progress';
import { Spinner } from '../components/feedback/Spinner';
import { Skeleton } from '../components/feedback/Skeleton';
import { useToast } from '../components/feedback/Toast';
import { Plus, Trash2, Settings } from 'lucide-react';

export const ComponentShowcase: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [buttonLoading, setButtonLoading] = useState(false);
  const toast = useToast();

  const handleLoadingDemo = () => {
    setButtonLoading(true);
    setTimeout(() => {
      setButtonLoading(false);
      toast.success('Completed', 'Async button action finished successfully.');
    }, 1500);
  };

  const actionsTab = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div>
        <h4 style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: '10px' }}>
          Button Variants
        </h4>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <Button variant="primary">Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">Danger</Button>
          <Button variant="primary" disabled>
            Disabled
          </Button>
          <Button variant="primary" isLoading={buttonLoading} onClick={handleLoadingDemo}>
            Click for Loading
          </Button>
        </div>
      </div>

      <div>
        <h4 style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: '10px' }}>
          Button Sizes &amp; Icons
        </h4>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <Button size="sm" leftIcon={<Plus size={14} />}>
            Small
          </Button>
          <Button size="md" leftIcon={<Plus size={16} />}>
            Medium
          </Button>
          <Button size="lg" leftIcon={<Plus size={18} />}>
            Large
          </Button>
          <IconButton icon={<Settings size={16} />} aria-label="Settings" variant="outline" />
          <IconButton icon={<Trash2 size={16} />} aria-label="Delete" variant="danger" />
          <SplitButton
            variant="primary"
            onClick={() => toast.info('Primary Action', 'Clicked split button default')}
            menuItems={[
              {
                id: 'exp_pdf',
                label: 'Export as PDF',
                onClick: () => toast.success('Export', 'Exported PDF'),
              },
              {
                id: 'exp_csv',
                label: 'Export as CSV',
                onClick: () => toast.success('Export', 'Exported CSV'),
              },
            ]}
          >
            Export Options
          </SplitButton>
        </div>
      </div>
    </div>
  );

  const feedbackTab = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div>
        <h4 style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: '10px' }}>Toasts</h4>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <Button
            variant="outline"
            size="sm"
            onClick={() => toast.success('Success', 'Operation completed.')}
          >
            Success Toast
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => toast.warning('Warning', 'Check invoice limits.')}
          >
            Warning Toast
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => toast.error('Error', 'Connection rejected by host.')}
          >
            Error Toast
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => toast.info('Info', 'System update pending.')}
          >
            Info Toast
          </Button>
        </div>
      </div>

      <div>
        <h4 style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: '10px' }}>
          Inline Alerts
        </h4>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <Alert severity="info" title="System Notice">
            BusinessOS UI Foundation is active with zero-downtime ledger routing.
          </Alert>
          <Alert severity="success" title="Authorization Policy Verified">
            All enterprise permissions synchronized with backend evaluation gateway.
          </Alert>
          <Alert severity="warning" title="Fiscal Period Closing">
            Financial ledger for period Q3 closes in 48 hours.
          </Alert>
          <Alert severity="danger" title="Validation Failure">
            Transaction batch #9042 exceeded operating site limit.
          </Alert>
        </div>
      </div>

      <div>
        <h4 style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: '10px' }}>
          Spinners &amp; Skeletons
        </h4>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '12px' }}>
          <Spinner size="sm" />
          <Spinner size="md" />
          <Spinner size="lg" />
        </div>
        <div style={{ maxWidth: '300px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <Skeleton variant="text" width="60%" />
          <Skeleton variant="rectangular" height="60px" />
        </div>
      </div>

      <div>
        <h4 style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: '10px' }}>
          Progress Bar
        </h4>
        <div style={{ maxWidth: '400px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <Progress value={65} label="Reconciliation Progress" showValue />
          <Progress label="Indeterminate Operation" />
        </div>
      </div>
    </div>
  );

  const overlaysTab = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div>
        <h4 style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: '10px' }}>
          Modal &amp; Drawer
        </h4>
        <div style={{ display: 'flex', gap: '12px' }}>
          <Button variant="primary" onClick={() => setIsModalOpen(true)}>
            Open Standard Modal
          </Button>
          <Button variant="secondary" onClick={() => setIsDrawerOpen(true)}>
            Open Side Drawer
          </Button>
        </div>
      </div>

      <div>
        <h4 style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: '10px' }}>Tooltips</h4>
        <div style={{ display: 'flex', gap: '16px' }}>
          <Tooltip content="Tooltip positioned on top">
            <Button variant="outline" size="sm">
              Hover Me (Top)
            </Button>
          </Tooltip>
          <Tooltip content="Tooltip positioned on right" position="right">
            <Button variant="outline" size="sm">
              Hover Me (Right)
            </Button>
          </Tooltip>
        </div>
      </div>
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          Design System &amp; Component Showcase
        </h1>
        <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
          Interactive catalog of accessible enterprise UI foundation primitives.
        </p>
      </div>

      <Card>
        <Tabs
          items={[
            { id: 'actions', label: 'Actions & Buttons', content: actionsTab },
            { id: 'feedback', label: 'Feedback & States', content: feedbackTab },
            { id: 'overlays', label: 'Overlays & Dialogs', content: overlaysTab },
          ]}
        />
      </Card>

      {/* Modal Dialog */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title="Enterprise Configuration Modal"
        description="Verify changes to organization operating parameters."
        footer={
          <>
            <Button variant="secondary" onClick={() => setIsModalOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                setIsModalOpen(false);
                toast.success('Saved', 'Configuration parameters updated.');
              }}
            >
              Confirm Changes
            </Button>
          </>
        }
      >
        <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)', lineHeight: 1.6 }}>
          Modals are fully accessible with automated keyboard focus trap, backdrop dismissal, Escape
          key detection, and high-contrast styling conforming with WCAG AA.
        </p>
      </Modal>

      {/* Side Drawer */}
      <Drawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        title="Contextual Inspector"
        footer={
          <Button
            variant="primary"
            onClick={() => setIsDrawerOpen(false)}
            style={{ width: '100%' }}
          >
            Close Inspector
          </Button>
        }
      >
        <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)', lineHeight: 1.6 }}>
          Drawers slide in smoothly from the screen edge with backdrop dimming and provide
          structured deep-dive inspection surfaces.
        </p>
      </Drawer>
    </div>
  );
};
