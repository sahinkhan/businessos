import { SessionInfo, UserProfile } from '../../src/auth/types';
import { TenantScope } from '../../src/scope/types';

export const TEST_USER: UserProfile = {
  id: 'principal_test',
  email: 'operator@example.test',
  name: 'Test Operator',
  tenantId: 'tenant_one',
  principal: {
    id: 'principal_test',
    tenantId: 'tenant_one',
    type: 'user',
    authenticationStrength: 'oidc',
  },
};

export const TEST_SESSION: SessionInfo = {
  principal: TEST_USER.principal,
  activeScope: { tenantId: 'tenant_one' },
  expiresAt: Math.floor(Date.now() / 1000) + 3600,
  csrfToken: 'test_csrf_token',
};

export const TEST_TENANTS: TenantScope[] = [
  {
    id: 'tenant_one',
    name: 'Tenant One',
    groups: [
      {
        id: 'group_one',
        name: 'Group One',
        companies: [
          {
            id: 'company_one',
            name: 'Company One',
            code: 'ONE',
            currency: 'USD',
            sites: [
              { id: 'site_one', name: 'Site One', code: 'S1' },
              { id: 'site_two', name: 'Site Two', code: 'S2' },
            ],
          },
          {
            id: 'company_two',
            name: 'Company Two',
            code: 'TWO',
            currency: 'USD',
            sites: [{ id: 'site_three', name: 'Site Three', code: 'S3' }],
          },
        ],
      },
    ],
  },
  {
    id: 'tenant_two',
    name: 'Tenant Two',
    groups: [
      {
        id: 'group_two',
        name: 'Group Two',
        companies: [
          {
            id: 'company_three',
            name: 'Company Three',
            code: 'THREE',
            currency: 'EUR',
            sites: [{ id: 'site_four', name: 'Site Four', code: 'S4' }],
          },
        ],
      },
    ],
  },
];
