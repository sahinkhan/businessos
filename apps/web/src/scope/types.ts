export interface OperatingSite {
  id: string;
  name: string;
  code: string;
}

export interface LegalEntity {
  id: string;
  name: string;
  code: string;
  currency: string;
  sites: OperatingSite[];
}

export interface EnterpriseGroup {
  id: string;
  name: string;
  companies: LegalEntity[];
}

export interface TenantScope {
  id: string;
  name: string;
  groups: EnterpriseGroup[];
}

export interface ActiveScope {
  tenantId: string;
  tenantName: string;
  groupId: string;
  groupName: string;
  legalEntityId?: string | null;
  companyId: string;
  companyName: string;
  siteId: string;
  siteName: string;
}

export type ScopeStatus = 'idle' | 'loading' | 'ready' | 'unavailable' | 'switching';

export interface ScopeContextValue {
  scope: ActiveScope | null;
  tenants: TenantScope[];
  status: ScopeStatus;
  error: string | null;
  setTenant: (tenantId: string) => Promise<void>;
  setCompany: (companyId: string) => Promise<void>;
  setSite: (siteId: string) => Promise<void>;
  setScope: (scope: Partial<ActiveScope>) => Promise<void>;
}
