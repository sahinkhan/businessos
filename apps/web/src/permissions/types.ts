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
  constraints?: Record<string, any> | null;
}

export interface FieldAccessDecision {
  fieldName: string;
  readable: boolean;
  writable: boolean;
  masked: boolean;
  maskPattern?: string | null;
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

export interface ApprovalLimitResult {
  limit: number;
  currency: string;
}

export interface PermissionContextValue {
  canPerformAction: (action: string, resource: string) => boolean;
  getFieldPolicy: (resource: string, fieldName: string) => FieldPolicyHint;
  getActionEvaluation: (action: string, resource: string) => AuthorizeActionResult;
  registerPolicyDecisions?: (decisions: Record<string, AuthorizationDecision>) => void;
  registerFieldDecisions?: (decisions: Record<string, FieldAccessDecision>) => void;
}
