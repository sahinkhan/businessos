import { apiClient } from '../api/client';
import { ApiError } from '../api/types';
import { AuthResponse, SessionInfo, UserProfile } from './types';

export interface AuthAdapter {
  login(credentials: { email: string; password?: string }): Promise<AuthResponse>;
  validateSession(accessToken: string): Promise<AuthResponse | null>;
  logout(accessToken?: string): Promise<void>;
  refreshSession(accessToken: string): Promise<SessionInfo>;
}

function isAuthResponse(value: unknown): value is AuthResponse {
  if (typeof value !== 'object' || value === null) return false;
  const response = value as Partial<AuthResponse>;
  return Boolean(
    response.user?.id &&
    response.user.email &&
    response.session?.accessToken &&
    typeof response.session.expiresAt === 'number' &&
    typeof response.session.issuedAt === 'number'
  );
}

export class HttpAuthAdapter implements AuthAdapter {
  constructor(private readonly baseUrl = '/api/v1/auth') {}

  public async login(credentials: { email: string; password?: string }): Promise<AuthResponse> {
    try {
      const response = await apiClient.post<unknown>(`${this.baseUrl}/login`, credentials);
      if (!isAuthResponse(response)) throw new Error('Malformed backend session response');
      return response;
    } catch (caught: unknown) {
      if (caught instanceof ApiError && caught.status === 401) {
        throw new Error('Invalid email or password.');
      }
      throw caught;
    }
  }

  public async validateSession(accessToken: string): Promise<AuthResponse | null> {
    try {
      const response = await apiClient.get<unknown>(`${this.baseUrl}/session`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      return isAuthResponse(response) ? response : null;
    } catch {
      return null;
    }
  }

  public async logout(accessToken?: string): Promise<void> {
    await apiClient.post(
      `${this.baseUrl}/logout`,
      undefined,
      accessToken ? { headers: { Authorization: `Bearer ${accessToken}` } } : undefined
    );
  }

  public async refreshSession(accessToken: string): Promise<SessionInfo> {
    const response = await apiClient.post<unknown>(`${this.baseUrl}/refresh`, undefined, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (
      typeof response !== 'object' ||
      response === null ||
      typeof (response as Partial<SessionInfo>).accessToken !== 'string' ||
      typeof (response as Partial<SessionInfo>).expiresAt !== 'number' ||
      typeof (response as Partial<SessionInfo>).issuedAt !== 'number'
    ) {
      throw new Error('Malformed backend session refresh response');
    }
    return response as SessionInfo;
  }
}

export class MockAuthAdapter implements AuthAdapter {
  constructor(
    private readonly mockUser: UserProfile,
    private mockSession: SessionInfo
  ) {}

  public async login(): Promise<AuthResponse> {
    return { user: this.mockUser, session: this.mockSession };
  }

  public async validateSession(accessToken: string): Promise<AuthResponse | null> {
    return accessToken === this.mockSession.accessToken
      ? { user: this.mockUser, session: this.mockSession }
      : null;
  }

  public async logout(): Promise<void> {}

  public async refreshSession(): Promise<SessionInfo> {
    this.mockSession = {
      ...this.mockSession,
      issuedAt: Math.floor(Date.now() / 1000),
      expiresAt: Math.floor(Date.now() / 1000) + 3600,
    };
    return this.mockSession;
  }
}

export const defaultAuthAdapter = new HttpAuthAdapter();
