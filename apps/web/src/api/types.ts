export interface ApiErrorPayload {
  code: string;
  message: string;
  details?: unknown;
  correlationId?: string;
}

export class ApiError extends Error {
  public readonly code: string;
  public readonly status: number;
  public readonly details?: unknown;
  public readonly correlationId?: string;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message || 'API request failed');
    this.name = 'ApiError';
    this.status = status;
    this.code = payload.code || 'UNKNOWN_ERROR';
    this.details = payload.details;
    this.correlationId = payload.correlationId;
  }
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined>;
  scope?: {
    tenantId?: string;
    legalEntityId?: string;
    companyId?: string;
    siteId?: string;
  };
}
