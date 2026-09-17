import { describe, it, expect } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { AuthProvider } from '../../src/auth/AuthContext';
import { PermissionProvider } from '../../src/permissions/PermissionContext';
import { PermissionBoundary } from '../../src/permissions/PermissionBoundary';
import { FieldPolicyWrapper } from '../../src/permissions/FieldPolicyWrapper';
import { Button } from '../../src/components/actions/Button';
import { MockPolicyAdapter } from '../../src/permissions/policyAdapter';
import { UserProfile, SessionInfo } from '../../src/auth/types';

const authenticatedUser: UserProfile = {
  id: 'usr_controller_1',
  email: 'controller@businessos.internal',
  name: 'Financial Controller',
  roles: ['controller'],
  tenantId: 'tenant_default',
  principal: {
    tenantId: 'tenant_default',
    principalId: 'usr_controller_1',
    principalType: 'user',
    authenticationStrength: 'password',
    scopes: [{ tenant_id: 'tenant_default' }],
  },
};

const validSession: SessionInfo = {
  token: 'bos_token_ctrl',
  issuedAt: Math.floor(Date.now() / 1000),
  expiresAt: Math.floor(Date.now() / 1000) + 3600,
};

describe('Permission Boundary Foundation (Phase 4 Policy Presentation)', () => {
  it('renders content when backend policy decision grants authorization', () => {
    const policyAdapter = new MockPolicyAdapter({
      'ledger:delete': {
        allowed: true,
        reason: 'Authorized by policy_financial_controller',
        matchedPolicy: 'policy_financial_controller',
      },
    });

    render(
      <AuthProvider initialUser={authenticatedUser} initialSession={validSession}>
        <PermissionProvider adapter={policyAdapter}>
          <PermissionBoundary action="delete" resource="ledger">
            <Button>Authorized Delete</Button>
          </PermissionBoundary>
        </PermissionProvider>
      </AuthProvider>
    );

    expect(screen.getByText('Authorized Delete')).toBeInTheDocument();
  });

  it('denies by default when no policy grant exists', async () => {
    const emptyPolicyAdapter = new MockPolicyAdapter();

    await act(async () => {
      render(
        <AuthProvider initialUser={authenticatedUser} initialSession={validSession}>
          <PermissionProvider adapter={emptyPolicyAdapter}>
            <PermissionBoundary
              action="delete"
              resource="restricted_vault"
              fallback={<div>Access Denied</div>}
            >
              <Button>Vault Button</Button>
            </PermissionBoundary>
          </PermissionProvider>
        </AuthProvider>
      );
    });

    expect(screen.queryByText('Vault Button')).not.toBeInTheDocument();
    expect(screen.getByText('Access Denied')).toBeInTheDocument();
  });

  it('masks sensitive fields according to Phase 4 FieldAccessDecision', () => {
    const policyAdapter = new MockPolicyAdapter(
      {},
      {
        'employee.ssn': {
          fieldName: 'ssn',
          readable: true,
          writable: false,
          masked: true,
        },
        'employee.secretKey': {
          fieldName: 'secretKey',
          readable: false,
          writable: false,
          masked: false,
        },
      }
    );

    render(
      <AuthProvider initialUser={authenticatedUser} initialSession={validSession}>
        <PermissionProvider adapter={policyAdapter}>
          <div>
            <FieldPolicyWrapper resource="employee" field="ssn">
              <span data-testid="raw-ssn">123-45-6789</span>
            </FieldPolicyWrapper>
            <FieldPolicyWrapper resource="employee" field="secretKey">
              <span data-testid="secret-key">TOP_SECRET</span>
            </FieldPolicyWrapper>
          </div>
        </PermissionProvider>
      </AuthProvider>
    );

    // Raw SSN should not be rendered; mask placeholder should be rendered
    expect(screen.queryByTestId('raw-ssn')).not.toBeInTheDocument();
    expect(screen.getByText('••••••••')).toBeInTheDocument();

    // Unreadable field should not be rendered at all
    expect(screen.queryByTestId('secret-key')).not.toBeInTheDocument();
  });
});
