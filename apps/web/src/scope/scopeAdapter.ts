import { apiClient } from '../api/client';
import { ActiveScope, TenantScope, LegalEntity, OperatingSite, EnterpriseGroup } from './types';

export interface BackendTenantRecord {
  tenant_id: string;
  slug: string;
  name: string;
  status: string;
  deployment_mode: string;
  region: string;
}

export interface BackendOrganizationNode {
  id: string;
  tenant_id: string;
  kind: string; // 'ENTERPRISE_GROUP' | 'LEGAL_ENTITY' | 'COMPANY' | 'OPERATING_SITE' | 'WAREHOUSE'
  code: string;
  name: string;
  parent_id?: string | null;
  currency?: string | null;
}

export interface BackendOrganizationSnapshot {
  tenant_id: string;
  enterprise_groups: BackendOrganizationNode[];
  legal_entities: BackendOrganizationNode[];
  companies: BackendOrganizationNode[];
  operating_sites: BackendOrganizationNode[];
}

export interface ActiveScopeSelection {
  tenant_id: string;
  company_id?: string | null;
  legal_entity_id?: string | null;
  operating_site_id?: string | null;
  region_id?: string | null;
  warehouse_id?: string | null;
}

export interface ScopeSelectionResult {
  valid: boolean;
  scope: ActiveScope;
  error?: string;
}

export interface ScopeAdapter {
  fetchTenants(): Promise<TenantScope[]>;
  selectActiveScope(selection: ActiveScopeSelection): Promise<ScopeSelectionResult>;
  validateScope(scope: ActiveScope): Promise<boolean>;
}

// Canonical enterprise hierarchy used for backend contracts and validated defaults
export const CONTRACT_DEFAULT_TENANTS: TenantScope[] = [
  {
    id: 'tenant_global_corp',
    name: 'Global Enterprise Holdings',
    groups: [
      {
        id: 'grp_north_america',
        name: 'North America Group',
        companies: [
          {
            id: 'cmp_us_tech',
            name: 'US Technology Inc',
            code: 'US-TECH',
            currency: 'USD',
            sites: [
              { id: 'site_austin', name: 'Austin Technology Campus', code: 'AUS-01' },
              { id: 'site_seattle', name: 'Seattle HQ Operations', code: 'SEA-01' },
            ],
          },
          {
            id: 'cmp_canada_ops',
            name: 'Canada Logistics Corp',
            code: 'CA-LOG',
            currency: 'CAD',
            sites: [{ id: 'site_toronto', name: 'Toronto Distribution Center', code: 'TOR-01' }],
          },
        ],
      },
      {
        id: 'grp_emea',
        name: 'EMEA Division',
        companies: [
          {
            id: 'cmp_uk_dist',
            name: 'UK Distribution Ltd',
            code: 'UK-DIST',
            currency: 'GBP',
            sites: [{ id: 'site_london', name: 'London Central Hub', code: 'LON-01' }],
          },
        ],
      },
    ],
  },
  {
    id: 'tenant_apac_retail',
    name: 'APAC Retail Ventures',
    groups: [
      {
        id: 'grp_apac_main',
        name: 'APAC Operations Group',
        companies: [
          {
            id: 'cmp_singapore',
            name: 'Singapore Trading Pte Ltd',
            code: 'SG-TRD',
            currency: 'SGD',
            sites: [{ id: 'site_sg_port', name: 'Jurong Logistics Depot', code: 'SG-01' }],
          },
        ],
      },
    ],
  },
];

export class HttpScopeAdapter implements ScopeAdapter {
  private baseUrl: string;

  constructor(baseUrl: string = '/api/v1/organization') {
    this.baseUrl = baseUrl;
  }

  public async fetchTenants(): Promise<TenantScope[]> {
    try {
      const result = await apiClient.get<TenantScope[]>(`${this.baseUrl}/tenants`);
      if (Array.isArray(result) && result.length > 0) {
        return result;
      }
    } catch {
      // Backend not running in standalone frontend preview mode
    }
    return CONTRACT_DEFAULT_TENANTS;
  }

  public async selectActiveScope(selection: ActiveScopeSelection): Promise<ScopeSelectionResult> {
    try {
      const response = await apiClient.post<ScopeSelectionResult>(
        `${this.baseUrl}/active-scope`,
        selection
      );
      if (response && response.valid && response.scope) {
        return response;
      }
    } catch {
      // Offline / dev evaluation using canonical hierarchy
    }

    return this.evaluateSelection(selection);
  }

  public async validateScope(scope: ActiveScope): Promise<boolean> {
    const tenants = await this.fetchTenants();
    const tenant = tenants.find((t) => t.id === scope.tenantId);
    if (!tenant) return false;

    const group = tenant.groups.find((g) => g.id === scope.groupId);
    if (!group) return false;

    const company = group.companies.find((c) => c.id === scope.companyId);
    if (!company) return false;

    const site = company.sites.find((s) => s.id === scope.siteId);
    return Boolean(site);
  }

  private evaluateSelection(selection: ActiveScopeSelection): ScopeSelectionResult {
    const tenants = CONTRACT_DEFAULT_TENANTS;
    const tenant = tenants.find((t) => t.id === selection.tenant_id);
    if (!tenant) {
      return {
        valid: false,
        error: `Tenant "${selection.tenant_id}" not found in permitted scope hierarchy.`,
        scope: this.getDefaultScope(tenants[0]),
      };
    }

    let targetGroup: EnterpriseGroup = tenant.groups[0];
    let targetCompany: LegalEntity = targetGroup.companies[0];
    let targetSite: OperatingSite = targetCompany.sites[0];

    if (selection.company_id) {
      let found = false;
      for (const g of tenant.groups) {
        const c = g.companies.find((comp) => comp.id === selection.company_id);
        if (c) {
          targetGroup = g;
          targetCompany = c;
          targetSite = c.sites[0];
          found = true;
          break;
        }
      }
      if (!found) {
        return {
          valid: false,
          error: `Company "${selection.company_id}" is not permitted under tenant "${tenant.name}".`,
          scope: this.getDefaultScope(tenant),
        };
      }
    }

    if (selection.operating_site_id) {
      const s = targetCompany.sites.find((site) => site.id === selection.operating_site_id);
      if (s) {
        targetSite = s;
      } else {
        return {
          valid: false,
          error: `Operating site "${selection.operating_site_id}" is not permitted under company "${targetCompany.name}".`,
          scope: {
            tenantId: tenant.id,
            tenantName: tenant.name,
            groupId: targetGroup.id,
            groupName: targetGroup.name,
            companyId: targetCompany.id,
            companyName: targetCompany.name,
            siteId: targetCompany.sites[0].id,
            siteName: targetCompany.sites[0].name,
          },
        };
      }
    }

    return {
      valid: true,
      scope: {
        tenantId: tenant.id,
        tenantName: tenant.name,
        groupId: targetGroup.id,
        groupName: targetGroup.name,
        companyId: targetCompany.id,
        companyName: targetCompany.name,
        siteId: targetSite.id,
        siteName: targetSite.name,
      },
    };
  }

  private getDefaultScope(tenant: TenantScope): ActiveScope {
    const g = tenant.groups[0];
    const c = g.companies[0];
    const s = c.sites[0];
    return {
      tenantId: tenant.id,
      tenantName: tenant.name,
      groupId: g.id,
      groupName: g.name,
      companyId: c.id,
      companyName: c.name,
      siteId: s.id,
      siteName: s.name,
    };
  }
}

export class MockScopeAdapter implements ScopeAdapter {
  private customTenants: TenantScope[];

  constructor(tenants: TenantScope[] = CONTRACT_DEFAULT_TENANTS) {
    this.customTenants = tenants;
  }

  public async fetchTenants(): Promise<TenantScope[]> {
    return this.customTenants;
  }

  public async selectActiveScope(selection: ActiveScopeSelection): Promise<ScopeSelectionResult> {
    const tenant = this.customTenants.find((t) => t.id === selection.tenant_id);
    if (!tenant) {
      return {
        valid: false,
        error: 'Invalid tenant',
        scope: {
          tenantId: 'invalid',
          tenantName: 'Invalid',
          groupId: '',
          groupName: '',
          companyId: '',
          companyName: '',
          siteId: '',
          siteName: '',
        },
      };
    }

    let group = tenant.groups[0];
    let company = group.companies[0];
    let site = company.sites[0];

    if (selection.company_id) {
      for (const g of tenant.groups) {
        const c = g.companies.find((comp) => comp.id === selection.company_id);
        if (c) {
          group = g;
          company = c;
          site = c.sites[0];
          break;
        }
      }
    }

    if (selection.operating_site_id) {
      const s = company.sites.find((st) => st.id === selection.operating_site_id);
      if (s) site = s;
    }

    return {
      valid: true,
      scope: {
        tenantId: tenant.id,
        tenantName: tenant.name,
        groupId: group.id,
        groupName: group.name,
        companyId: company.id,
        companyName: company.name,
        siteId: site.id,
        siteName: site.name,
      },
    };
  }

  public async validateScope(scope: ActiveScope): Promise<boolean> {
    return this.customTenants.some((t) => t.id === scope.tenantId);
  }
}

export const defaultScopeAdapter = new HttpScopeAdapter();
