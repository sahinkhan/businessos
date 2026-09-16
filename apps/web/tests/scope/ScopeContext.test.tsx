import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ScopeProvider, useScope } from '../../src/scope/ScopeContext';

const TestScopeComponent = () => {
  const { scope, setTenant, setCompany, tenants } = useScope();
  return (
    <div>
      <div data-testid="tenant">{scope.tenantName}</div>
      <div data-testid="company">{scope.companyName}</div>
      <button onClick={() => setTenant(tenants[1].id)}>Switch to APAC</button>
      <button onClick={() => setCompany('cmp_canada_ops')}>Switch to Canada</button>
    </div>
  );
};

describe('Scope & Entity Isolation Foundation', () => {
  it('provides default active scope and permits switching entities', () => {
    render(
      <ScopeProvider>
        <TestScopeComponent />
      </ScopeProvider>
    );

    expect(screen.getByTestId('tenant')).toHaveTextContent('Global Enterprise Holdings');
    expect(screen.getByTestId('company')).toHaveTextContent('US Technology Inc');

    // Switch tenant
    fireEvent.click(screen.getByText('Switch to APAC'));
    expect(screen.getByTestId('tenant')).toHaveTextContent('APAC Retail Ventures');
    expect(screen.getByTestId('company')).toHaveTextContent('Singapore Trading Pte Ltd');
  });
});
