export interface FieldPolicyHint {
  readable: boolean;
  writable: boolean;
  masked: boolean;
}

export interface AuthorizeActionResult {
  allowed: boolean;
  reason?: string;
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
}
