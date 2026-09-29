import { createHash, randomBytes, randomUUID, timingSafeEqual } from 'node:crypto';
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Plugin } from 'vite';

type DemoRole = 'admin' | 'viewer';
type DemoSession = {
  id: string;
  csrf: string;
  email: string;
  role: DemoRole;
  companyId: string;
  siteId: string;
  expiresAt: number;
};

const TENANT_ID = '00000000-0000-4000-8000-000000000101';
const GROUP_ID = '00000000-0000-4000-8000-000000000102';
const COMPANIES = [
  {
    id: '00000000-0000-4000-8000-000000000103',
    name: 'Northstar Bangladesh Ltd',
    code: 'NS-BD',
    currency: 'BDT',
    sites: [{ id: '00000000-0000-4000-8000-000000000104', name: 'Dhaka HQ', code: 'DHK' }],
  },
  {
    id: '00000000-0000-4000-8000-000000000105',
    name: 'Northstar UAE LLC',
    code: 'NS-AE',
    currency: 'AED',
    sites: [{ id: '00000000-0000-4000-8000-000000000106', name: 'Dubai Office', code: 'DXB' }],
  },
] as const;
const USERS = {
  'admin@demo.businessos.test': {
    id: '00000000-0000-4000-8000-000000000107',
    name: 'Amina Rahman',
    role: 'admin',
  },
  'viewer@demo.businessos.test': {
    id: '00000000-0000-4000-8000-000000000108',
    name: 'Samir Hassan',
    role: 'viewer',
  },
} as const;

function json(response: ServerResponse, status: number, body: object, cookie?: string) {
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    ...(cookie ? { 'Set-Cookie': cookie } : {}),
  });
  response.end(JSON.stringify(body));
}

function cookieValue(request: IncomingMessage): string | null {
  const match = /(?:^|;\s*)bos_demo_session=([^;]*)/.exec(request.headers.cookie ?? '');
  return match?.[1] ?? null;
}

function sameOrigin(request: IncomingMessage): boolean {
  const origin = request.headers.origin;
  const host = request.headers.host;
  const fetchSite = request.headers['sec-fetch-site'];
  return (
    Boolean(host) &&
    (!origin || origin === `http://${host}`) &&
    (!fetchSite || fetchSite === 'same-origin' || fetchSite === 'none')
  );
}

async function body(request: IncomingMessage): Promise<Record<string, unknown>> {
  let content = '';
  for await (const chunk of request) {
    content += chunk.toString();
    if (content.length > 4096) throw new Error('Request too large');
  }
  const parsed: unknown = JSON.parse(content);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
    throw new Error('Invalid body');
  return parsed as Record<string, unknown>;
}

function secureEqual(left: string, right: string): boolean {
  const leftHash = createHash('sha256').update(left).digest();
  const rightHash = createHash('sha256').update(right).digest();
  return timingSafeEqual(leftHash, rightHash);
}

const freshToken = () => randomBytes(32).toString('base64url');
const sessionCookie = (token: string) =>
  `bos_demo_session=${token}; Path=/api; HttpOnly; SameSite=Strict; Max-Age=3600`;
const expiredCookie = 'bos_demo_session=; Path=/api; HttpOnly; SameSite=Strict; Max-Age=0';

/** Local Vite-only preview API. Never registered with the production ASGI application. */
export function demoApiPlugin(password: string): Plugin {
  if (
    process.env.NODE_ENV === 'production' ||
    (process.env.BOS_ENVIRONMENT && process.env.BOS_ENVIRONMENT !== 'development')
  ) {
    throw new Error('The local demo API is unavailable outside development');
  }
  if (!password) throw new Error('The local demo password is required');
  const sessions = new Map<string, DemoSession>();

  return {
    name: 'businessos-local-demo-api',
    apply: 'serve',
    configureServer(server) {
      if (server.config.server.host !== '127.0.0.1') {
        throw new Error('The local demo API must bind only to 127.0.0.1');
      }
      server.middlewares.use('/api', async (request, response, next) => {
        const pathname = new URL(request.url ?? '/', 'http://localhost').pathname;
        const method = request.method ?? 'GET';
        const token = cookieValue(request);
        let session = token ? sessions.get(token) : undefined;
        if (session && session.expiresAt <= Date.now()) {
          sessions.delete(token!);
          session = undefined;
        }

        if (method === 'POST' && !sameOrigin(request)) {
          json(response, 403, { code: 'invalid_origin' });
          return;
        }
        if (pathname === '/dev/demo-login' && method === 'POST') {
          try {
            const input = await body(request);
            const email = typeof input.email === 'string' ? input.email.trim().toLowerCase() : '';
            const candidate = typeof input.password === 'string' ? input.password : '';
            const user = USERS[email as keyof typeof USERS];
            if (!user || !secureEqual(candidate, password)) {
              json(response, 401, { code: 'invalid_demo_credentials' });
              return;
            }
            if (token) sessions.delete(token);
            const newToken = freshToken();
            sessions.set(newToken, {
              id: randomUUID(),
              csrf: freshToken(),
              email,
              role: user.role,
              companyId: COMPANIES[0].id,
              siteId: COMPANIES[0].sites[0].id,
              expiresAt: Date.now() + 60 * 60 * 1000,
            });
            json(response, 200, { status: 'authenticated' }, sessionCookie(newToken));
          } catch {
            json(response, 400, { code: 'invalid_request' });
          }
          return;
        }

        if (pathname === '/v1/auth/session' && method === 'GET') {
          if (!session) {
            json(response, 401, { code: 'unauthenticated' }, expiredCookie);
            return;
          }
          const user = USERS[session.email as keyof typeof USERS];
          json(response, 200, {
            status: 'authenticated',
            session_id: session.id,
            csrf_token: session.csrf,
            expires_at: new Date(session.expiresAt).toISOString(),
            principal: {
              id: user.id,
              tenant_id: TENANT_ID,
              display_name: user.name,
              email: session.email,
            },
            active_scope: {
              tenant_id: TENANT_ID,
              company_id: session.companyId,
              operating_site_id: session.siteId,
            },
          });
          return;
        }

        if (!session) {
          json(response, 401, { code: 'unauthenticated' });
          return;
        }
        if (method === 'POST' && request.headers['x-csrf-token'] !== session.csrf) {
          json(response, 403, { code: 'invalid_csrf' });
          return;
        }
        if (pathname === '/v1/auth/logout' && method === 'POST') {
          sessions.delete(token!);
          json(response, 200, { status: 'signed_out' }, expiredCookie);
          return;
        }
        if (pathname === '/v1/organization/scopes' && method === 'GET') {
          const company = COMPANIES.find((item) => item.id === session.companyId)!;
          const site = company.sites.find((item) => item.id === session.siteId)!;
          json(response, 200, {
            tenants: [
              {
                id: TENANT_ID,
                name: 'Northstar Holdings',
                groups: [{ id: GROUP_ID, name: 'Northstar Group', companies: COMPANIES }],
              },
            ],
            active_scope: {
              tenantId: TENANT_ID,
              tenantName: 'Northstar Holdings',
              groupId: GROUP_ID,
              groupName: 'Northstar Group',
              companyId: company.id,
              companyName: company.name,
              siteId: site.id,
              siteName: site.name,
            },
          });
          return;
        }
        if (pathname === '/v1/organization/active-scope' && method === 'POST') {
          try {
            const input = await body(request);
            const company = COMPANIES.find((item) => item.id === input.company_id);
            const site = company?.sites.find((item) => item.id === input.operating_site_id);
            if (input.tenant_id !== TENANT_ID || input.enterprise_group_id !== GROUP_ID || !site) {
              json(response, 403, { code: 'invalid_scope' });
              return;
            }
            sessions.delete(token!);
            const newToken = freshToken();
            sessions.set(newToken, {
              ...session,
              id: randomUUID(),
              csrf: freshToken(),
              companyId: company!.id,
              siteId: site.id,
            });
            json(response, 200, { status: 'selected' }, sessionCookie(newToken));
          } catch {
            json(response, 400, { code: 'invalid_request' });
          }
          return;
        }
        if (pathname === '/v1/policy/authorize' && method === 'POST') {
          try {
            const input = await body(request);
            json(response, 200, {
              allowed:
                session.role === 'admin' &&
                input.action === 'read' &&
                input.resource_type === 'system.settings',
            });
          } catch {
            json(response, 400, { code: 'invalid_request' });
          }
          return;
        }
        if (pathname === '/v1/policy/field-access' && method === 'POST') {
          json(response, 200, { readable: false, writable: false, masked: true });
          return;
        }
        if (pathname.startsWith('/dev/') || pathname.startsWith('/v1/')) {
          json(response, 404, { code: 'not_found' });
          return;
        }
        next();
      });
    },
  };
}
