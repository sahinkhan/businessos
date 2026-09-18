import { apiClient } from '../api/client';
import { ActiveScope, TenantScope } from './types';

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
  scope?: ActiveScope;
  csrfToken?: string;
  expiresAt?: number;
  error?: string;
}

export interface ScopeAdapter {
  fetchTenants(): Promise<TenantScope[]>;
  selectActiveScope(selection: ActiveScopeSelection): Promise<ScopeSelectionResult>;
  validateScope(scope: ActiveScope): Promise<boolean>;
}

function nodeList(value: unknown): Array<{ id: string; name: string; code: string }> | null {
  if (!Array.isArray(value)) return null;
  const result = value.filter(
    (node): node is { id: string; name: string; code: string } =>
      typeof node === 'object' &&
      node !== null &&
      typeof (node as Record<string, unknown>).id === 'string' &&
      typeof (node as Record<string, unknown>).name === 'string' &&
      typeof (node as Record<string, unknown>).code === 'string'
  );
  return result.length === value.length ? result : null;
}

function hierarchyProjection(value: unknown): TenantScope[] | null {
  if (typeof value !== 'object' || value === null) return null;
  const snapshot = value as Record<string, unknown>;
  if (typeof snapshot.tenant_id !== 'string') return null;
  const groups = nodeList(snapshot.enterprise_groups);
  const companies = nodeList(snapshot.companies);
  const sites = nodeList(snapshot.operating_sites);
  if (!groups || !companies || !sites) return null;
  const groupNodes =
    groups.length > 0 ? groups : [{ id: snapshot.tenant_id, name: 'Organization', code: '' }];
  return [
    {
      id: snapshot.tenant_id,
      name: snapshot.tenant_id,
      groups: groupNodes.map((group) => ({
        id: group.id,
        name: group.name,
        companies: companies.map((company) => ({
          id: company.id,
          name: company.name,
          code: company.code,
          currency: '',
          sites,
        })),
      })),
    },
  ];
}

function isActiveScope(value: unknown): value is ActiveScope {
  if (typeof value !== 'object' || value === null) return false;
  const scope = value as Partial<ActiveScope>;
  return Boolean(scope.tenantId && scope.tenantName);
}

export class HttpScopeAdapter implements ScopeAdapter {
  private hierarchy: TenantScope[] = [];

  constructor(private readonly baseUrl = '/organization') {}

  public async fetchTenants(): Promise<TenantScope[]> {
    const response = hierarchyProjection(await apiClient.get<unknown>(`${this.baseUrl}/hierarchy`));
    if (!response) throw new Error('Malformed backend organization hierarchy response');
    this.hierarchy = response;
    return response;
  }

  public async selectActiveScope(selection: ActiveScopeSelection): Promise<ScopeSelectionResult> {
    const response = await apiClient.post<unknown>(`${this.baseUrl}/active-scope`, selection);
    if (typeof response !== 'object' || response === null) {
      throw new Error('Malformed backend active-scope response');
    }
    const candidate = response as Record<string, unknown>;
    if (
      candidate.valid !== true ||
      typeof candidate.scope !== 'object' ||
      candidate.scope === null
    ) {
      return {
        valid: false,
        error: typeof candidate.error === 'string' ? candidate.error : 'Scope selection rejected',
      };
    }
    const scope = candidate.scope as Record<string, unknown>;
    const tenant = this.hierarchy.find((item) => item.id === scope.tenant_id);
    const group = tenant?.groups.find((item) => item.id === scope.enterprise_group_id);
    const companies = tenant?.groups.flatMap((item) => item.companies) ?? [];
    const company = companies.find(
      (item) => item.id === (scope.company_id ?? scope.legal_entity_id)
    );
    const site = companies
      .flatMap((item) => item.sites)
      .find((item) => item.id === scope.operating_site_id);
    const active: ActiveScope = {
      tenantId: String(scope.tenant_id ?? ''),
      tenantName: tenant?.name ?? String(scope.tenant_id ?? ''),
      groupId: typeof scope.enterprise_group_id === 'string' ? scope.enterprise_group_id : null,
      groupName: group?.name ?? null,
      legalEntityId: typeof scope.legal_entity_id === 'string' ? scope.legal_entity_id : null,
      companyId: typeof scope.company_id === 'string' ? scope.company_id : null,
      companyName: company?.name ?? null,
      siteId: typeof scope.operating_site_id === 'string' ? scope.operating_site_id : null,
      siteName: site?.name ?? null,
    };
    if (!isActiveScope(active)) return { valid: false, error: 'Malformed backend active scope' };
    const expiresAt =
      typeof candidate.expires_at === 'string' ? Date.parse(candidate.expires_at) / 1000 : NaN;
    if (typeof candidate.csrf_token !== 'string' || !Number.isFinite(expiresAt)) {
      return { valid: false, error: 'Malformed backend session rotation response' };
    }
    return {
      valid: true,
      scope: active,
      csrfToken: candidate.csrf_token,
      expiresAt,
    };
  }

  public async validateScope(scope: ActiveScope): Promise<boolean> {
    const response = await apiClient.post<unknown>(`${this.baseUrl}/validate-scope`, {
      tenant_id: scope.tenantId,
      legal_entity_id: scope.legalEntityId,
      company_id: scope.companyId,
      operating_site_id: scope.siteId,
    });
    return (
      typeof response === 'object' &&
      response !== null &&
      (response as Record<string, unknown>).valid === true
    );
  }
}

export const defaultScopeAdapter = new HttpScopeAdapter();
