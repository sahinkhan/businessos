import { apiClient } from '../api/client';
import { AuthorizationDecision, FieldAccessDecision, ApprovalAuthorityDecision } from './types';

export interface PolicyEvaluationQuery {
  principalId?: string;
  action: string;
  resourceType: string;
  resourceId?: string;
  scope?: {
    tenantId?: string;
    companyId?: string;
    siteId?: string;
  };
  context?: Record<string, any>;
}

export interface PolicyPresentationAdapter {
  evaluateAuthorization(query: PolicyEvaluationQuery): Promise<AuthorizationDecision>;
  evaluateFieldAccess(
    resourceType: string,
    fieldName: string,
    scope?: { tenantId?: string; companyId?: string; siteId?: string }
  ): Promise<FieldAccessDecision>;
  evaluateApprovalAuthority(
    approvalType: string,
    amount: number,
    currency: string,
    scope?: { tenantId?: string; companyId?: string; siteId?: string }
  ): Promise<ApprovalAuthorityDecision>;
  getPreloadedAuthorization(action: string, resource: string): AuthorizationDecision | null;
  getPreloadedFieldAccess(resource: string, fieldName: string): FieldAccessDecision | null;
  setPreloadedDecisions(decisions: Record<string, AuthorizationDecision>): void;
  setPreloadedFields(decisions: Record<string, FieldAccessDecision>): void;
}

export class HttpPolicyAdapter implements PolicyPresentationAdapter {
  private baseUrl: string;
  private preloadedDecisions: Map<string, AuthorizationDecision> = new Map();
  private preloadedFields: Map<string, FieldAccessDecision> = new Map();

  constructor(baseUrl: string = '/api/v1/policy') {
    this.baseUrl = baseUrl;
  }

  public setPreloadedDecisions(decisions: Record<string, AuthorizationDecision>): void {
    for (const [k, v] of Object.entries(decisions)) {
      this.preloadedDecisions.set(k, v);
    }
  }

  public setPreloadedFields(decisions: Record<string, FieldAccessDecision>): void {
    for (const [k, v] of Object.entries(decisions)) {
      this.preloadedFields.set(k, v);
    }
  }

  public getPreloadedAuthorization(action: string, resource: string): AuthorizationDecision | null {
    const key = `${resource}:${action}`;
    return this.preloadedDecisions.get(key) || null;
  }

  public getPreloadedFieldAccess(resource: string, fieldName: string): FieldAccessDecision | null {
    const key = `${resource}.${fieldName}`;
    return this.preloadedFields.get(key) || null;
  }

  public async evaluateAuthorization(query: PolicyEvaluationQuery): Promise<AuthorizationDecision> {
    const key = `${query.resourceType}:${query.action}`;
    const preloaded = this.preloadedDecisions.get(key);
    if (preloaded) return preloaded;

    try {
      const decision = await apiClient.post<AuthorizationDecision>(
        `${this.baseUrl}/authorize`,
        query
      );
      if (decision && typeof decision.allowed === 'boolean') {
        this.preloadedDecisions.set(key, decision);
        return decision;
      }
    } catch {
      // Backend policy engine unreachable
    }

    // Phase 4 default: Deny by default
    return {
      allowed: false,
      reason: `Deny by default: no active policy decision grants ${query.resourceType}:${query.action}`,
      matchedPolicy: null,
    };
  }

  public async evaluateFieldAccess(
    resourceType: string,
    fieldName: string,
    scope?: { tenantId?: string; companyId?: string; siteId?: string }
  ): Promise<FieldAccessDecision> {
    const key = `${resourceType}.${fieldName}`;
    const preloaded = this.preloadedFields.get(key);
    if (preloaded) return preloaded;

    try {
      const decision = await apiClient.post<FieldAccessDecision>(`${this.baseUrl}/field-access`, {
        resource_type: resourceType,
        field_name: fieldName,
        scope,
      });
      if (decision) {
        this.preloadedFields.set(key, decision);
        return decision;
      }
    } catch {
      // Backend policy engine unreachable
    }

    return {
      fieldName,
      readable: true,
      writable: true,
      masked: false,
    };
  }

  public async evaluateApprovalAuthority(
    approvalType: string,
    amount: number,
    currency: string,
    scope?: { tenantId?: string; companyId?: string; siteId?: string }
  ): Promise<ApprovalAuthorityDecision> {
    try {
      const decision = await apiClient.post<ApprovalAuthorityDecision>(
        `${this.baseUrl}/approval-limit`,
        {
          approval_type: approvalType,
          amount,
          currency,
          scope,
        }
      );
      if (decision) return decision;
    } catch {
      // Backend policy engine unreachable
    }

    return {
      hasAuthority: false,
      limit: 0,
      currency,
      reason: 'Deny by default: no active approval policy for principal',
    };
  }
}

export class MockPolicyAdapter implements PolicyPresentationAdapter {
  private decisions: Map<string, AuthorizationDecision> = new Map();
  private fields: Map<string, FieldAccessDecision> = new Map();

  constructor(
    initialDecisions?: Record<string, AuthorizationDecision>,
    initialFields?: Record<string, FieldAccessDecision>
  ) {
    if (initialDecisions) {
      for (const [k, v] of Object.entries(initialDecisions)) {
        this.decisions.set(k, v);
      }
    }
    if (initialFields) {
      for (const [k, v] of Object.entries(initialFields)) {
        this.fields.set(k, v);
      }
    }
  }

  public setPreloadedDecisions(decisions: Record<string, AuthorizationDecision>): void {
    for (const [k, v] of Object.entries(decisions)) {
      this.decisions.set(k, v);
    }
  }

  public setPreloadedFields(decisions: Record<string, FieldAccessDecision>): void {
    for (const [k, v] of Object.entries(decisions)) {
      this.fields.set(k, v);
    }
  }

  public getPreloadedAuthorization(action: string, resource: string): AuthorizationDecision | null {
    return this.decisions.get(`${resource}:${action}`) || null;
  }

  public getPreloadedFieldAccess(resource: string, fieldName: string): FieldAccessDecision | null {
    return this.fields.get(`${resource}.${fieldName}`) || null;
  }

  public async evaluateAuthorization(query: PolicyEvaluationQuery): Promise<AuthorizationDecision> {
    const key = `${query.resourceType}:${query.action}`;
    const found = this.decisions.get(key);
    if (found) return found;

    return {
      allowed: false,
      reason: `Deny by default: no active policy decision grants ${query.resourceType}:${query.action}`,
      matchedPolicy: null,
    };
  }

  public async evaluateFieldAccess(
    resourceType: string,
    fieldName: string
  ): Promise<FieldAccessDecision> {
    const key = `${resourceType}.${fieldName}`;
    const found = this.fields.get(key);
    if (found) return found;

    return {
      fieldName,
      readable: true,
      writable: true,
      masked: false,
    };
  }

  public async evaluateApprovalAuthority(
    _approvalType: string,
    amount: number,
    currency: string
  ): Promise<ApprovalAuthorityDecision> {
    return {
      hasAuthority: amount <= 10000,
      limit: 10000,
      currency,
      reason: amount <= 10000 ? 'Within approved threshold' : 'Exceeds approval delegation limit',
    };
  }
}

export const defaultPolicyAdapter = new HttpPolicyAdapter();
