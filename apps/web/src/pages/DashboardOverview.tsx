import React from 'react';
import { DashboardPageShell } from '../layouts/DashboardPageShell';
import { Card } from '../components/structure/Card';
import { Grid } from '../components/structure/Grid';
import { Button } from '../components/actions/Button';
import { useScope } from '../scope/ScopeContext';
import { useAuth } from '../auth/AuthContext';
import { useToast } from '../components/feedback/Toast';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../i18n/I18nContext';
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
  const { t } = useI18n();

  return (
    <DashboardPageShell title={t('dashboard.title')}>
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
              {t('dashboard.connected_context')}: <strong>{scope.tenantName}</strong> &gt;{' '}
              <strong>{scope.companyName}</strong> ({scope.siteName})
            </span>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                toast.info(
                  t('dashboard.diagnostics_title'),
                  t('dashboard.diagnostics_correlation', {
                    id: 'corr_' + Math.random().toString(36).substring(2, 8),
                  })
                )
              }
            >
              {t('dashboard.copy_diagnostics')}
            </Button>
            <Button
              variant="primary"
              size="sm"
              leftIcon={<Plus size={14} />}
              onClick={() =>
                toast.success(t('dashboard.action_triggered'), t('dashboard.batch_initiated'))
              }
            >
              {t('dashboard.quick_action')}
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
              {t('dashboard.active_legal_entity')}
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
            <span>{t('dashboard.site_active')}</span>
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
              {t('dashboard.authenticated_user')}
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
              {t('dashboard.system_status')}
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
            {t('dashboard.foundation_version')}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
            {t('dashboard.system_description')}
          </div>
        </Card>
      </Grid>

      {/* Quick Access to Foundation Demos */}
      <Card title={t('dashboard.demos_title')} subtitle={t('dashboard.demos_subtitle')}>
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
              {t('dashboard.showcase_title')}
            </h4>
            <p
              style={{
                fontSize: '0.8125rem',
                color: 'var(--color-text-secondary)',
                marginTop: '4px',
              }}
            >
              {t('dashboard.showcase_description')}
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
              {t('dashboard.table_title')}
            </h4>
            <p
              style={{
                fontSize: '0.8125rem',
                color: 'var(--color-text-secondary)',
                marginTop: '4px',
              }}
            >
              {t('dashboard.table_description')}
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
              {t('dashboard.forms_title')}
            </h4>
            <p
              style={{
                fontSize: '0.8125rem',
                color: 'var(--color-text-secondary)',
                marginTop: '4px',
              }}
            >
              {t('dashboard.forms_description')}
            </p>
          </div>
        </Grid>
      </Card>
    </DashboardPageShell>
  );
};
