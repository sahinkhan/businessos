import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { I18nProvider } from '../../src/i18n/I18nContext';
import { en } from '../../src/i18n/translations/en';
import { ar } from '../../src/i18n/translations/ar';
import { es } from '../../src/i18n/translations/es';
import { DashboardOverview } from '../../src/pages/DashboardOverview';
import { SessionExpiryModal } from '../../src/auth/SessionExpiryModal';
import { useAuth } from '../../src/auth/AuthContext';
import { useScope } from '../../src/scope/ScopeContext';

vi.mock('../../src/auth/AuthContext', () => ({ useAuth: vi.fn() }));
vi.mock('../../src/scope/ScopeContext', () => ({ useScope: vi.fn() }));
vi.mock('../../src/components/feedback/Toast', () => ({
  useToast: () => ({ info: vi.fn(), success: vi.fn() }),
}));

function authenticated(expiresAt = Date.now() / 1000 + 3600): ReturnType<typeof useAuth> {
  const user = { id: 'user-a', name: 'User A', tenantId: 'tenant-a' };
  return {
    user,
    session: {
      id: 'session-a',
      user,
      tenantId: 'tenant-a',
      companyId: 'company-a',
      siteId: 'site-a',
      csrfToken: 'csrf-a',
      expiresAt,
    },
    status: 'authenticated',
    isAuthenticated: true,
    isLoading: false,
    login: async () => {},
    refreshToken: async () => {},
    logout: async () => {},
  };
}

const sharedKeys = [
  'common.close_dialog',
  'scope.switch',
  'scope.select',
  'scope.selector',
  'scope.tenant',
  'scope.entities_sites',
  'session.expiration_warning',
  'session.logout_now',
  'session.extend',
  'session.expires_one',
  'session.expires_many',
  'dashboard.title',
  'dashboard.connected_context',
  'dashboard.diagnostics_title',
  'dashboard.diagnostics_correlation',
  'dashboard.copy_diagnostics',
  'dashboard.action_triggered',
  'dashboard.batch_initiated',
  'dashboard.quick_action',
  'dashboard.active_legal_entity',
  'dashboard.site_active',
  'dashboard.authenticated_user',
  'dashboard.system_status',
  'dashboard.foundation_version',
  'dashboard.system_description',
  'dashboard.demos_title',
  'dashboard.demos_subtitle',
  'dashboard.showcase_title',
  'dashboard.showcase_description',
  'dashboard.table_title',
  'dashboard.table_description',
  'dashboard.forms_title',
  'dashboard.forms_description',
];

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe('Phase 4.5 shared UI translations', () => {
  it('has native English, Arabic, and Spanish values for every targeted key', () => {
    for (const key of sharedKeys) {
      expect(en[key], `Missing English ${key}`).toBeTruthy();
      expect(ar[key], `Missing Arabic ${key}`).toBeTruthy();
      expect(es[key], `Missing Spanish ${key}`).toBeTruthy();
      expect(ar[key]).not.toBe(en[key]);
      expect(es[key]).not.toBe(en[key]);
    }
    for (const key of ['session.expires_one', 'session.expires_many']) {
      for (const dictionary of [en, ar, es]) expect(dictionary[key]).toContain('{minutes}');
    }
    for (const dictionary of [en, ar, es])
      expect(dictionary['dashboard.diagnostics_correlation']).toContain('{id}');
    expect(en['dashboard.foundation_version']).toBe('UI Foundation v1');
  });

  it('renders the dashboard in Arabic RTL without premature certification copy', async () => {
    vi.mocked(useAuth).mockReturnValue(authenticated());
    vi.mocked(useScope).mockReturnValue({
      scope: {
        tenantId: 'tenant-a',
        tenantName: 'Tenant A',
        groupId: 'group-a',
        groupName: 'Group A',
        companyId: 'company-a',
        companyName: 'Company A',
        siteId: 'site-a',
        siteName: 'Site A',
      },
    } as ReturnType<typeof useScope>);
    render(
      <MemoryRouter>
        <I18nProvider defaultLocale="ar">
          <DashboardOverview />
        </I18nProvider>
      </MemoryRouter>
    );
    await waitFor(() => expect(document.documentElement.dir).toBe('rtl'));
    expect(
      screen.getByRole('heading', { name: 'نظرة عامة على العمليات المؤسسية' })
    ).toBeInTheDocument();
    expect(screen.getByText('أساس الواجهة الإصدار 1')).toBeInTheDocument();
    expect(screen.getByText('استكشف مكونات الواجهة المؤسسية وتخطيطاتها')).toBeInTheDocument();
    expect(screen.queryByText('Phase 4.5 Certified')).not.toBeInTheDocument();
  });

  it('renders the session warning and minute interpolation in Arabic RTL', async () => {
    vi.useFakeTimers();
    vi.mocked(useAuth).mockReturnValue(authenticated(Date.now() / 1000 + 120));
    render(
      <I18nProvider defaultLocale="ar">
        <SessionExpiryModal />
      </I18nProvider>
    );
    act(() => vi.advanceTimersByTime(5000));
    expect(document.documentElement.dir).toBe('rtl');
    expect(screen.getByRole('dialog', { name: 'تنبيه انتهاء الجلسة' })).toBeInTheDocument();
    expect(screen.getByText(/ستنتهي جلستك النشطة خلال نحو/)).toHaveTextContent(
      `${new Intl.NumberFormat('ar').format(2)} دقائق`
    );
    expect(screen.getByRole('button', { name: 'تمديد الجلسة' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'إغلاق مربع الحوار' })).toBeInTheDocument();
  });
});
