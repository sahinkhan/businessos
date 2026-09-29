import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nProvider } from '../../src/i18n/I18nContext';
import { ScopeSwitcher } from '../../src/scope/ScopeSwitcher';
import { useScope } from '../../src/scope/ScopeContext';
import type { ScopeContextValue } from '../../src/scope/types';

vi.mock('../../src/scope/ScopeContext', () => ({ useScope: vi.fn() }));

const setCompany = vi.fn();
const setSite = vi.fn();
const scope = {
  tenantId: 'tenant-a',
  tenantName: 'Tenant A',
  groupId: 'group-a',
  groupName: 'Group A',
  companyId: '',
  companyName: '',
  siteId: '',
  siteName: '',
};
const tenants = [
  {
    id: 'tenant-a',
    name: 'Tenant A',
    groups: [
      {
        id: 'group-a',
        name: 'Group A',
        companies: [
          { id: 'company-x', name: 'Company X', code: 'X', currency: 'USD', sites: [] },
          {
            id: 'company-y',
            name: 'Company Y',
            code: 'Y',
            currency: 'USD',
            sites: [{ id: 'site-y', name: 'Site Y', code: 'SY' }],
          },
        ],
      },
    ],
  },
];

function provideScope(
  override: Partial<ScopeContextValue['scope']> = {},
  availableTenants = tenants
) {
  vi.mocked(useScope).mockReturnValue({
    scope: { ...scope, ...override },
    tenants: availableTenants,
    isLoading: false,
    setTenant: vi.fn(),
    setCompany,
    setSite,
    setScope: vi.fn(),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  provideScope();
});

describe('scope switcher keyboard operation', () => {
  it('keeps the selector unavailable without backend-provided choices', () => {
    provideScope({}, []);
    render(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    expect(screen.getByRole('button', { name: 'Switch organization scope' })).toBeDisabled();
  });

  it('opens, selects a company with Enter, and selects a site with Space', async () => {
    const user = userEvent.setup();
    const view = render(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );

    await user.tab();
    const trigger = screen.getByRole('button', { name: 'Switch organization scope' });
    expect(trigger).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('dialog', { name: 'Scope Selector' })).toBeInTheDocument();

    await user.tab();
    expect(screen.getByRole('combobox', { name: 'TENANT' })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Company X (X)' })).toHaveFocus();
    await user.tab();
    const company = screen.getByRole('button', { name: 'Company Y (Y)' });
    expect(company).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(setCompany).toHaveBeenCalledExactlyOnceWith('company-y');

    provideScope({ companyId: 'company-y', companyName: 'Company Y' });
    view.rerender(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    expect(screen.getByRole('button', { name: 'Company Y (Y)' })).toHaveAttribute(
      'aria-current',
      'true'
    );
    await user.tab();
    const site = screen.getByRole('button', { name: '• Site Y' });
    expect(site).toHaveFocus();
    await user.keyboard(' ');
    expect(setSite).toHaveBeenCalledExactlyOnceWith('site-y');
    expect(screen.queryByRole('dialog', { name: 'Scope Selector' })).not.toBeInTheDocument();
  });

  it('renders Arabic labels, RTL direction, and usable company/site buttons', async () => {
    const user = userEvent.setup();
    provideScope({ companyId: 'company-y', companyName: 'Company Y' });
    render(
      <I18nProvider defaultLocale="ar">
        <ScopeSwitcher />
      </I18nProvider>
    );

    await waitFor(() => expect(document.documentElement.dir).toBe('rtl'));
    await user.tab();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('dialog', { name: 'محدد النطاق' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'المستأجر' })).toBeInTheDocument();
    expect(screen.getByText('الكيانات القانونية والمواقع')).toBeInTheDocument();
    const company = screen.getByRole('button', { name: 'Company Y (Y)' });
    const site = screen.getByRole('button', { name: '• Site Y' });
    expect(company).toHaveAttribute('aria-current', 'true');
    await user.click(site);
    expect(setSite).toHaveBeenCalledExactlyOnceWith('site-y');
  });
});
