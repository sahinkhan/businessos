import { apiClient } from '../api/client';
import { securityContext } from '../api/securityContext';
import {
  ApprovalAuthorityDecision,
  AuthorizationDecision,
  FieldAccessDecision,
  PolicySecurityContext,
} from './types';

export interface PolicyEvaluationQuery extends PolicySecurityContext {
  action: string;
  resourceType: string;
  resourceId?: string;
  context?: Record<string, unknown>;
}

export interface PolicyPresentationAdapter {
  evaluateAuthorization(query: PolicyEvaluationQuery): Promise<AuthorizationDecision>;
  evaluateFieldAccess(
    resourceType: string,
    fieldName: string,
    _context: PolicySecurityContext
  ): Promise<FieldAccessDecision>;
  evaluateApprovalAuthority(
    approvalType: string,
    amount: number,
    currency: string,
    context: PolicySecurityContext
  ): Promise<ApprovalAuthorityDecision>;
  getCachedAuthorization(
    action: string,
    resource: string,
    context: PolicySecurityContext
  ): AuthorizationDecision | null;
  getCachedFieldAccess(
    resource: string,
    fieldName: string,
    context: PolicySecurityContext
  ): FieldAccessDecision | null;
  clearCache(): void;
}

function contextKey(context: PolicySecurityContext): string {
  return [
    context.principalId,
    context.tenantId,
    context.legalEntityId ?? '',
    context.companyId ?? '',
    context.siteId ?? '',
  ].join('|');
}

function authorizationKey(
  action: string,
  resource: string,
  context: PolicySecurityContext
): string {
  return `${contextKey(context)}|${resource}|${action}`;
}

function fieldKey(resource: string, fieldName: string, context: PolicySecurityContext): string {
  return `${contextKey(context)}|${resource}|${fieldName}`;
}

const deniedField = (fieldName: string): FieldAccessDecision => ({
  fieldName,
  readable: false,
  writable: false,
  masked: true,
});

function normalizeAuthorization(value: unknown): AuthorizationDecision | null {
  if (typeof value !== 'object' || value === null) return null;
  const decision = value as Record<string, unknown>;
  if (typeof decision.allowed !== 'boolean' || typeof decision.reason !== 'string') return null;
  const matchedPolicy =
    typeof decision.matched_policy === 'string'
      ? decision.matched_policy
      : typeof decision.matchedPolicy === 'string'
        ? decision.matchedPolicy
        : null;
  return { allowed: decision.allowed, reason: decision.reason, matchedPolicy };
}

interface BackendFieldDecision {
  allowed: boolean;
  accessType: 'read' | 'write' | 'mask' | 'deny';
  maskPattern: string | null;
}

function normalizeBackendField(value: unknown): BackendFieldDecision | null {
  if (typeof value !== 'object' || value === null) return null;
  const decision = value as Record<string, unknown>;
  const accessType =
    typeof decision.access_type === 'string'
      ? decision.access_type
      : typeof decision.accessType === 'string'
        ? decision.accessType
        : null;
  if (
    typeof decision.allowed !== 'boolean' ||
    !accessType ||
    !['read', 'write', 'mask', 'deny'].includes(accessType)
  ) {
    return null;
  }
  return {
    allowed: decision.allowed,
    accessType: accessType as BackendFieldDecision['accessType'],
    maskPattern:
      typeof decision.mask_pattern === 'string'
        ? decision.mask_pattern
        : typeof decision.maskPattern === 'string'
          ? decision.maskPattern
          : null,
  };
}

export class HttpPolicyAdapter implements PolicyPresentationAdapter {
  private readonly authorizations = new Map<string, AuthorizationDecision>();
  private readonly fields = new Map<string, FieldAccessDecision>();

  constructor(private readonly baseUrl = '/policy') {}

  public getCachedAuthorization(
    action: string,
    resource: string,
    context: PolicySecurityContext
  ): AuthorizationDecision | null {
    return this.authorizations.get(authorizationKey(action, resource, context)) ?? null;
  }

  public getCachedFieldAccess(
    resource: string,
    fieldName: string,
    context: PolicySecurityContext
  ): FieldAccessDecision | null {
    return this.fields.get(fieldKey(resource, fieldName, context)) ?? null;
  }

  public clearCache(): void {
    this.authorizations.clear();
    this.fields.clear();
  }

  public async evaluateAuthorization(query: PolicyEvaluationQuery): Promise<AuthorizationDecision> {
    const key = authorizationKey(query.action, query.resourceType, query);
    const cached = this.authorizations.get(key);
    if (cached) return cached;

    const generation = securityContext.generation();
    const controller = securityContext.createAbortController();
    let decision: AuthorizationDecision;
    try {
      const response = await apiClient.post<unknown>(
        `${this.baseUrl}/authorize`,
        {
          action: query.action,
          resource: query.resourceType,
          record_scope_id: query.resourceId,
          attributes: query.context ?? {},
        },
        { signal: controller.signal }
      );
      decision = normalizeAuthorization(response) ?? {
        allowed: false,
        reason: 'Deny by default: malformed policy response',
        matchedPolicy: null,
      };
    } catch {
      decision = {
        allowed: false,
        reason: 'Deny by default: policy service unavailable',
        matchedPolicy: null,
      };
    }
    securityContext.release(controller);
    if (!controller.signal.aborted && generation === securityContext.generation()) {
      this.authorizations.set(key, decision);
    }
    return decision;
  }

  public async evaluateFieldAccess(
    resourceType: string,
    fieldName: string,
    context: PolicySecurityContext
  ): Promise<FieldAccessDecision> {
    const key = fieldKey(resourceType, fieldName, context);
    const cached = this.fields.get(key);
    if (cached) return cached;

    const generation = securityContext.generation();
    const controller = securityContext.createAbortController();
    let decision = deniedField(fieldName);
    const baseQuery = {
      resource_type: resourceType,
      field_name: fieldName,
      attributes: {
        legal_entity_id: context.legalEntityId,
        company_id: context.companyId,
        operating_site_id: context.siteId,
      },
    };
    try {
      const [readResponse, writeResponse] = await Promise.all([
        apiClient.post<unknown>(
          `${this.baseUrl}/field-access`,
          { ...baseQuery, requested_access: 'read' },
          { signal: controller.signal }
        ),
        apiClient.post<unknown>(
          `${this.baseUrl}/field-access`,
          { ...baseQuery, requested_access: 'write' },
          { signal: controller.signal }
        ),
      ]);
      const read = normalizeBackendField(readResponse);
      const write = normalizeBackendField(writeResponse);
      if (read && write) {
        decision = {
          fieldName,
          readable: read.allowed && read.accessType !== 'deny',
          writable: write.allowed && write.accessType === 'write',
          masked: read.allowed && read.accessType === 'mask',
          maskPattern: read.maskPattern,
        };
      }
    } catch {
      // A missing trusted Phase 4 decision remains fail closed.
    }
    securityContext.release(controller);
    if (!controller.signal.aborted && generation === securityContext.generation()) {
      this.fields.set(key, decision);
    }
    return decision;
  }

  public async evaluateApprovalAuthority(
    approvalType: string,
    amount: number,
    currency: string,
    _context: PolicySecurityContext
  ): Promise<ApprovalAuthorityDecision> {
    const generation = securityContext.generation();
    const controller = securityContext.createAbortController();
    try {
      const response = await apiClient.post<unknown>(
        `${this.baseUrl}/approval-limit`,
        { action_type: approvalType, amount, currency },
        { signal: controller.signal }
      );
      if (controller.signal.aborted || generation !== securityContext.generation()) {
        throw new Error('Stale security context');
      }
      if (typeof response === 'object' && response !== null) {
        const value = response as Record<string, unknown>;
        const hasAuthority =
          typeof value.has_authority === 'boolean' ? value.has_authority : value.hasAuthority;
        const limit =
          typeof value.limit === 'number'
            ? value.limit
            : typeof value.limit === 'string'
              ? Number(value.limit)
              : Number.NaN;
        if (
          typeof hasAuthority === 'boolean' &&
          Number.isFinite(limit) &&
          typeof value.currency === 'string' &&
          typeof value.reason === 'string'
        ) {
          return { hasAuthority, limit, currency: value.currency, reason: value.reason };
        }
      }
    } catch {
      // A missing trusted Phase 4 decision remains fail closed.
    } finally {
      securityContext.release(controller);
    }
    return {
      hasAuthority: false,
      limit: 0,
      currency,
      reason: 'Deny by default: approval policy unavailable',
    };
  }
}

export class MockPolicyAdapter implements PolicyPresentationAdapter {
  private readonly cache = new Map<string, AuthorizationDecision>();
  private readonly fieldCache = new Map<string, FieldAccessDecision>();

  constructor(
    private readonly decisions: Record<string, AuthorizationDecision> = {},
    private readonly fieldDecisions: Record<string, FieldAccessDecision> = {}
  ) {}

  public clearCache(): void {
    this.cache.clear();
    this.fieldCache.clear();
  }

  public getCachedAuthorization(
    action: string,
    resource: string,
    context: PolicySecurityContext
  ): AuthorizationDecision | null {
    return this.cache.get(authorizationKey(action, resource, context)) ?? null;
  }

  public getCachedFieldAccess(
    resource: string,
    fieldName: string,
    context: PolicySecurityContext
  ): FieldAccessDecision | null {
    return this.fieldCache.get(fieldKey(resource, fieldName, context)) ?? null;
  }

  public async evaluateAuthorization(query: PolicyEvaluationQuery): Promise<AuthorizationDecision> {
    const decision = this.decisions[`${query.resourceType}:${query.action}`] ?? {
      allowed: false,
      reason: 'Deny by default: no mock decision',
      matchedPolicy: null,
    };
    this.cache.set(authorizationKey(query.action, query.resourceType, query), decision);
    return decision;
  }

  public async evaluateFieldAccess(
    resourceType: string,
    fieldName: string,
    context: PolicySecurityContext
  ): Promise<FieldAccessDecision> {
    const decision = this.fieldDecisions[`${resourceType}.${fieldName}`] ?? deniedField(fieldName);
    this.fieldCache.set(fieldKey(resourceType, fieldName, context), decision);
    return decision;
  }

  public async evaluateApprovalAuthority(
    _approvalType: string,
    _amount: number,
    currency: string
  ): Promise<ApprovalAuthorityDecision> {
    return {
      hasAuthority: false,
      limit: 0,
      currency,
      reason: 'Deny by default: no mock approval decision',
    };
  }
}

export const defaultPolicyAdapter = new HttpPolicyAdapter();
