import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from '../../src/auth/AuthContext';
import { Drawer } from '../../src/components/overlays/Drawer';
import { ErrorState } from '../../src/components/feedback/ErrorState';
import { I18nProvider } from '../../src/i18n/I18nContext';
import { ScopeProvider, useScope } from '../../src/scope/ScopeContext';
import { MockScopeAdapter } from '../../src/scope/mockScopeAdapter';
import { ScopeAdapter, ScopeSelectionResult } from '../../src/scope/scopeAdapter';
import { TEST_SESSION, TEST_TENANTS } from '../fixtures/security';

const ScopeControls = () => {
  const { scope, status, setCompany } = useScope();
  const { session } = useAuth();
  return (
    <>
      <span data-testid="status">{status}</span>
      <span data-testid="company">{scope?.companyId}</span>
      <span data-testid="csrf">{session?.csrfToken}</span>
      <button onClick={() => void setCompany('company_two')}>Select B</button>
      <button onClick={() => void setCompany('company_one')}>Retain A</button>
    </>
  );
};

describe('independent certification boundary re-audit', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('reconciles server scope and CSRF after retaining A while a B mutation is pending', async () => {
    const mock = new MockScopeAdapter(TEST_TENANTS);
    let completeB!: (result: ScopeSelectionResult) => void;
    let serverCompany = 'company_one';
    let serverCsrf = 'csrf-a';
    const adapter: ScopeAdapter = {
      fetchTenants: () => mock.fetchTenants(),
      validateScope: async () => true,
      selectActiveScope: async (selection) => {
        if (selection.company_id === 'company_two') {
          return new Promise((resolve) => {
            completeB = resolve;
          });
        }
        const result = await mock.selectActiveScope(selection);
        if (result.valid && result.scope?.companyId) serverCompany = result.scope.companyId;
        return {
          ...result,
          csrfToken: serverCsrf,
          expiresAt: TEST_SESSION.expiresAt,
        };
      },
    };
    render(
      <AuthProvider initialSession={TEST_SESSION}>
        <ScopeProvider adapter={adapter}>
          <ScopeControls />
        </ScopeProvider>
      </AuthProvider>
    );
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('ready'));
    fireEvent.click(screen.getByText('Select B'));
    expect(screen.getByTestId('status')).toHaveTextContent('switching');
    fireEvent.click(screen.getByText('Retain A'));
    await act(async () => {
      // A selection POST commits server scope and rotates the cookie before its response.
      serverCompany = 'company_two';
      serverCsrf = 'csrf-b';
      completeB({
        ...(await mock.selectActiveScope({ tenant_id: 'tenant_one', company_id: serverCompany })),
        csrfToken: serverCsrf,
        expiresAt: TEST_SESSION.expiresAt,
      });
    });
    expect.soft(screen.getByTestId('company')).toHaveTextContent(serverCompany);
    expect(screen.getByTestId('csrf')).toHaveTextContent(serverCsrf);
  });

  it('retains controlled input focus in the reusable Drawer', () => {
    const Editor = () => {
      const [open, setOpen] = useState(true);
      const [name, setName] = useState('');
      return (
        <Drawer isOpen={open} onClose={() => setOpen(false)} title="Edit record">
          <input aria-label="Name" value={name} onChange={(event) => setName(event.target.value)} />
        </Drawer>
      );
    };
    render(<Editor />);
    const input = screen.getByRole('textbox', { name: 'Name' });
    input.focus();
    fireEvent.change(input, { target: { value: 'A' } });
    expect(input).toHaveValue('A');
    expect(input).toHaveFocus();
  });

  it('translates the production ErrorState retry control in Spanish', () => {
    render(
      <I18nProvider defaultLocale="es">
        <ErrorState onRetry={() => {}} />
      </I18nProvider>
    );
    expect(screen.getByRole('button')).toHaveAccessibleName('Reintentar');
  });
});
