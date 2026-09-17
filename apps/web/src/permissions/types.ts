export interface PolicySecurityContext {
  principalId: string;
  tenantId: string;
  legalEntityId?: string | null;
  companyId?: string | null;
  siteId?: string | null;
}

export interface FieldPolicyHint {
  readable: boolean;
  writable: boolean;
  masked: boolean;
  maskPattern?: string | null;
}

export interface AuthorizationDecision {
  allowed: boolean;
  reason: string;
  matchedPolicy?: string | null;
  constraints?: Record<string, unknown> | null;
}

export interface FieldAccessDecision extends FieldPolicyHint {
  fieldName: string;
}

export interface ApprovalAuthorityDecision {
  hasAuthority: boolean;
  limit: number;
  currency: string;
  reason: string;
}

export interface AuthorizeActionResult {
  allowed: boolean;
  reason?: string;
  matchedPolicy?: string | null;
  fields?: Record<string, FieldPolicyHint>;
}

export interface PermissionContextValue {
  canPerformAction: (action: string, resource: string) => boolean;
  getFieldPolicy: (resource: string, fieldName: string) => FieldPolicyHint;
  getActionEvaluation: (action: string, resource: string) => AuthorizeActionResult;
}
