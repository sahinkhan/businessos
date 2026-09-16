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
  companyId: string;
  companyName: string;
  siteId: string;
  siteName: string;
}

export interface ScopeContextValue {
  scope: ActiveScope;
  tenants: TenantScope[];
  setTenant: (tenantId: string) => void;
  setCompany: (companyId: string) => void;
  setSite: (siteId: string) => void;
  setScope: (scope: Partial<ActiveScope>) => void;
}
