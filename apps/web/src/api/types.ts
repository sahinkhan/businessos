export interface ApiErrorPayload {
  code: string;
  message: string;
  details?: any;
  correlationId?: string;
}

export class ApiError extends Error {
  public code: string;
  public status: number;
  public details?: any;
  public correlationId?: string;

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
  body?: any;
  params?: Record<string, string | number | boolean | undefined>;
  scope?: {
    tenantId?: string;
    companyId?: string;
    siteId?: string;
  };
}
