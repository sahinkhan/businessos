import React from 'react';
import { DashboardPageShell } from '../layouts/DashboardPageShell';
import { Card } from '../components/structure/Card';
import { Grid } from '../components/structure/Grid';
import { Button } from '../components/actions/Button';
import { useScope } from '../scope/ScopeContext';
import { useAuth } from '../auth/AuthContext';
import { useToast } from '../components/feedback/Toast';
import { useNavigate } from 'react-router-dom';
import {
  Building,
  Users,
  CheckCircle,
  ArrowUpRight,
  Plus,
  Table,
  Layers,
  CheckSquare,
} from 'lucide-react';

export const DashboardOverview: React.FC = () => {
  const { scope } = useScope();
  const { user } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();

  return (
    <DashboardPageShell title="Enterprise Operational Overview">
      {/* Scope banner */}
      <Card
        variant="outlined"
        padding="sm"
        style={{ backgroundColor: 'var(--color-surface-subtle)' }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '12px',
          }}
        >
          <div>
            <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-secondary)' }}>
              Connected Context: <strong>{scope.tenantName}</strong> &gt;{' '}
              <strong>{scope.companyName}</strong> ({scope.siteName})
            </span>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                toast.info(
                  'Diagnostics',
                  'Correlation ID: corr_' + Math.random().toString(36).substring(2, 8)
                )
              }
            >
              Copy Diagnostics
            </Button>
            <Button
              variant="primary"
              size="sm"
              leftIcon={<Plus size={14} />}
              onClick={() => toast.success('Action Triggered', 'New operational batch initiated')}
            >
              Quick Action
            </Button>
          </div>
        </div>
      </Card>

      {/* KPI Metrics */}
      <Grid columns={{ sm: 1, md: 3 }} gap={16}>
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span
              style={{
                fontSize: '0.8125rem',
                color: 'var(--color-text-secondary)',
                fontWeight: 500,
              }}
            >
              ACTIVE LEGAL ENTITY
            </span>
            <Building size={18} color="var(--color-action-primary)" />
          </div>
          <div
            style={{
              fontSize: '1.5rem',
              fontWeight: 700,
              margin: '8px 0 2px 0',
              color: 'var(--color-text-primary)',
            }}
          >
            {scope.companyName}
          </div>
          <div
            style={{
              fontSize: '0.75rem',
              color: 'var(--color-status-success)',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            <CheckCircle size={12} />
            <span>Operational site active</span>
          </div>
        </Card>

        <Card>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span
              style={{
                fontSize: '0.8125rem',
                color: 'var(--color-text-secondary)',
                fontWeight: 500,
              }}
            >
              AUTHENTICATED USER
            </span>
            <Users size={18} color="var(--color-action-primary)" />
          </div>
          <div
            style={{
              fontSize: '1.25rem',
              fontWeight: 700,
              margin: '8px 0 2px 0',
              color: 'var(--color-text-primary)',
            }}
          >
            {user?.name}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
            Roles: {user?.roles.join(', ')}
          </div>
        </Card>

        <Card>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span
              style={{
                fontSize: '0.8125rem',
                color: 'var(--color-text-secondary)',
                fontWeight: 500,
              }}
            >
              SYSTEM STATUS
            </span>
            <ArrowUpRight size={18} color="var(--color-status-success)" />
          </div>
          <div
            style={{
              fontSize: '1.5rem',
              fontWeight: 700,
              margin: '8px 0 2px 0',
              color: 'var(--color-text-primary)',
            }}
          >
            Phase 4.5 Certified
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
            Design System &amp; Core Shell v1
          </div>
        </Card>
      </Grid>

      {/* Quick Access to Foundation Demos */}
      <Card
        title="UI Foundation Interactive Demos"
        subtitle="Explore certified enterprise components and layouts"
      >
        <Grid columns={{ sm: 1, md: 3 }} gap={16}>
          <div
            onClick={() => navigate('/showcase')}
            style={{
              padding: '16px',
              borderRadius: '8px',
              backgroundColor: 'var(--color-surface-subtle)',
              cursor: 'pointer',
              border: '1px solid var(--color-border-subtle)',
            }}
          >
            <Layers size={24} color="var(--color-action-primary)" style={{ marginBottom: '8px' }} />
            <h4 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
              Component Showcase
            </h4>
            <p
              style={{
                fontSize: '0.8125rem',
                color: 'var(--color-text-secondary)',
                marginTop: '4px',
              }}
            >
              Buttons, badges, modals, drawers, tooltips, toasts, alerts, and tokens.
            </p>
          </div>

          <div
            onClick={() => navigate('/demo/datatable')}
            style={{
              padding: '16px',
              borderRadius: '8px',
              backgroundColor: 'var(--color-surface-subtle)',
              cursor: 'pointer',
              border: '1px solid var(--color-border-subtle)',
            }}
          >
            <Table size={24} color="var(--color-action-primary)" style={{ marginBottom: '8px' }} />
            <h4 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
              DataTable Foundation
            </h4>
            <p
              style={{
                fontSize: '0.8125rem',
                color: 'var(--color-text-secondary)',
                marginTop: '4px',
              }}
            >
              Sorting, filtering, bulk selection, column visibility, and pagination.
            </p>
          </div>

          <div
            onClick={() => navigate('/demo/forms')}
            style={{
              padding: '16px',
              borderRadius: '8px',
              backgroundColor: 'var(--color-surface-subtle)',
              cursor: 'pointer',
              border: '1px solid var(--color-border-subtle)',
            }}
          >
            <CheckSquare
              size={24}
              color="var(--color-action-primary)"
              style={{ marginBottom: '8px' }}
            />
            <h4 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
              Form &amp; Input Primitives
            </h4>
            <p
              style={{
                fontSize: '0.8125rem',
                color: 'var(--color-text-secondary)',
                marginTop: '4px',
              }}
            >
              Multi-input form with money, dates, validation errors, and dirty detection.
            </p>
          </div>
        </Grid>
      </Card>
    </DashboardPageShell>
  );
};
