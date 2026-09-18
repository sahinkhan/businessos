import { ActiveScopeSelection, ScopeAdapter, ScopeSelectionResult } from './scopeAdapter';
import { ActiveScope, TenantScope } from './types';

export class MockScopeAdapter implements ScopeAdapter {
  constructor(private readonly tenants: TenantScope[]) {}

  public async fetchTenants(): Promise<TenantScope[]> {
    return this.tenants;
  }

  public async selectActiveScope(selection: ActiveScopeSelection): Promise<ScopeSelectionResult> {
    const tenant = this.tenants.find((item) => item.id === selection.tenant_id);
    if (!tenant) return { valid: false, error: 'Tenant rejected' };

    let group = tenant.groups[0];
    let company = group?.companies[0];
    if (selection.company_id || selection.legal_entity_id) {
      const requested = selection.company_id ?? selection.legal_entity_id;
      const match = tenant.groups
        .flatMap((candidate) =>
          candidate.companies.map((entry) => ({ group: candidate, company: entry }))
        )
        .find(({ company: entry }) => entry.id === requested);
      if (!match) return { valid: false, error: 'Company rejected' };
      group = match.group;
      company = match.company;
    }
    if (!group || !company) return { valid: false, error: 'Hierarchy unavailable' };

    let site = company.sites[0];
    if (selection.operating_site_id) {
      const requestedSite = company.sites.find((entry) => entry.id === selection.operating_site_id);
      if (!requestedSite) return { valid: false, error: 'Operating site rejected' };
      site = requestedSite;
    }
    if (!site) return { valid: false, error: 'Operating site unavailable' };

    return {
      valid: true,
      scope: {
        tenantId: tenant.id,
        tenantName: tenant.name,
        groupId: group.id,
        groupName: group.name,
        legalEntityId: company.id,
        companyId: company.id,
        companyName: company.name,
        siteId: site.id,
        siteName: site.name,
      },
    };
  }

  public async validateScope(scope: ActiveScope): Promise<boolean> {
    const result = await this.selectActiveScope({
      tenant_id: scope.tenantId,
      legal_entity_id: scope.legalEntityId,
      company_id: scope.companyId,
      operating_site_id: scope.siteId,
    });
    return result.valid;
  }
}
