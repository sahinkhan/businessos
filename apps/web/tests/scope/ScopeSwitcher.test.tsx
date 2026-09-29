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
  availableTenants = tenants,
  isLoading = false
) {
  vi.mocked(useScope).mockReturnValue({
    scope: { ...scope, ...override },
    tenants: availableTenants,
    isLoading,
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

    provideScope({}, [], true);
    view.rerender(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    expect(screen.queryByRole('button', { name: '• Site Y' })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(document.body);

    provideScope({ companyId: 'company-y', companyName: 'Company Y', siteId: 'site-y' });
    view.rerender(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    expect(screen.getByRole('button', { name: 'Company Y (Y)' })).toHaveAttribute(
      'aria-current',
      'true'
    );
    const site = screen.getByRole('button', { name: '• Site Y' });
    await waitFor(() => expect(site).toHaveFocus());
    expect(document.activeElement).not.toBe(document.body);
    await user.keyboard(' ');
    expect(setSite).toHaveBeenCalledExactlyOnceWith('site-y');
    expect(screen.queryByRole('dialog', { name: 'Scope Selector' })).not.toBeInTheDocument();

    provideScope({}, [], true);
    view.rerender(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    expect(document.activeElement).toBe(document.body);
    provideScope({ companyId: 'company-y', companyName: 'Company Y', siteId: 'site-y' });
    view.rerender(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it('does not focus a stale site while company selection is pending or rejected', async () => {
    const user = userEvent.setup();
    provideScope({ companyId: 'company-x', companyName: 'Company X' });
    const view = render(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    await user.tab();
    await user.keyboard('{Enter}');
    await user.tab();
    await user.tab();
    await user.tab();
    await user.keyboard('{Enter}');
    expect(setCompany).toHaveBeenCalledExactlyOnceWith('company-y');

    provideScope({}, [], true);
    view.rerender(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    expect(screen.queryByRole('button', { name: '• Site Y' })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(document.body);

    provideScope({ companyId: 'company-x', companyName: 'Company X' });
    view.rerender(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Switch organization scope' })).toHaveFocus()
    );
    expect(screen.queryByRole('button', { name: '• Site Y' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Company Y (Y)' })).not.toHaveAttribute(
      'aria-current'
    );
  });

  it('accepts Space on a company and Enter on the authoritative site option', async () => {
    const user = userEvent.setup();
    const view = render(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    await user.tab();
    await user.keyboard('{Enter}');
    await user.tab();
    await user.tab();
    await user.tab();
    await user.keyboard(' ');
    expect(setCompany).toHaveBeenCalledExactlyOnceWith('company-y');

    provideScope({}, [], true);
    view.rerender(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    provideScope({ companyId: 'company-y', companyName: 'Company Y', siteId: 'site-y' });
    view.rerender(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    const site = screen.getByRole('button', { name: '• Site Y' });
    await waitFor(() => expect(site).toHaveFocus());
    await user.keyboard('{Enter}');
    expect(setSite).toHaveBeenCalledExactlyOnceWith('site-y');
  });

  it('keeps mouse company and site choices working without keyboard focus restoration', async () => {
    const user = userEvent.setup();
    const view = render(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    await user.click(screen.getByRole('button', { name: 'Switch organization scope' }));
    await user.click(screen.getByRole('button', { name: 'Company Y (Y)' }));
    expect(setCompany).toHaveBeenCalledExactlyOnceWith('company-y');
    provideScope({}, [], true);
    view.rerender(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    provideScope({ companyId: 'company-y', companyName: 'Company Y' });
    view.rerender(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    await user.click(screen.getByRole('button', { name: '• Site Y' }));
    expect(setSite).toHaveBeenCalledExactlyOnceWith('site-y');
    expect(screen.queryByRole('dialog', { name: 'Scope Selector' })).not.toBeInTheDocument();
  });

  it('closes with Escape and returns focus to the trigger', async () => {
    const user = userEvent.setup();
    render(
      <I18nProvider>
        <ScopeSwitcher />
      </I18nProvider>
    );
    await user.tab();
    const trigger = screen.getByRole('button', { name: 'Switch organization scope' });
    await user.keyboard('{Enter}');
    await user.tab();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Scope Selector' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
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
