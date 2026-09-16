import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AuthProvider } from '../../src/auth/AuthContext';
import { PermissionProvider } from '../../src/permissions/PermissionContext';
import { PermissionBoundary } from '../../src/permissions/PermissionBoundary';
import { Button } from '../../src/components/actions/Button';

describe('Permission Boundary Foundation', () => {
  it('renders content when user is admin/has wildcard permissions', () => {
    render(
      <AuthProvider>
        <PermissionProvider>
          <PermissionBoundary action="delete" resource="ledger">
            <Button>Authorized Delete</Button>
          </PermissionBoundary>
        </PermissionProvider>
      </AuthProvider>
    );

    expect(screen.getByText('Authorized Delete')).toBeInTheDocument();
  });
});
