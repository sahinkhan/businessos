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
  error?: string;
}

export interface ScopeAdapter {
  fetchTenants(): Promise<TenantScope[]>;
  selectActiveScope(selection: ActiveScopeSelection): Promise<ScopeSelectionResult>;
  validateScope(scope: ActiveScope): Promise<boolean>;
}

function isTenantList(value: unknown): value is TenantScope[] {
  return (
    Array.isArray(value) &&
    value.every(
      (tenant) =>
        typeof tenant === 'object' &&
        tenant !== null &&
        typeof (tenant as TenantScope).id === 'string' &&
        Array.isArray((tenant as TenantScope).groups)
    )
  );
}

function isActiveScope(value: unknown): value is ActiveScope {
  if (typeof value !== 'object' || value === null) return false;
  const scope = value as Partial<ActiveScope>;
  return Boolean(
    scope.tenantId &&
    scope.groupId &&
    scope.companyId &&
    scope.siteId &&
    scope.tenantName &&
    scope.companyName &&
    scope.siteName
  );
}

export class HttpScopeAdapter implements ScopeAdapter {
  constructor(private readonly baseUrl = '/api/v1/organization') {}

  public async fetchTenants(): Promise<TenantScope[]> {
    const response = await apiClient.get<unknown>(`${this.baseUrl}/tenants`);
    if (!isTenantList(response)) throw new Error('Malformed backend tenant scope response');
    return response;
  }

  public async selectActiveScope(selection: ActiveScopeSelection): Promise<ScopeSelectionResult> {
    const response = await apiClient.post<unknown>(`${this.baseUrl}/active-scope`, selection);
    if (typeof response !== 'object' || response === null) {
      throw new Error('Malformed backend active-scope response');
    }
    const candidate = response as Record<string, unknown>;
    if (candidate.valid !== true || !isActiveScope(candidate.scope)) {
      return {
        valid: false,
        error: typeof candidate.error === 'string' ? candidate.error : 'Scope selection rejected',
      };
    }
    return { valid: true, scope: candidate.scope };
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
