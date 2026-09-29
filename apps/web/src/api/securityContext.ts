import { queryCache } from './queryCache';

/** Only a validated server session may populate this in-memory request context. */
export interface SecurityIdentity {
  sessionId: string;
  userId: string;
  tenantId: string;
  companyId: string | null;
  siteId: string | null;
  csrfToken: string;
}

let identity: SecurityIdentity | null = null;
let generation = 0;
const controllers = new Set<AbortController>();

export const securityContext = {
  current: () => identity,
  generation: () => generation,
  key: () =>
    identity
      ? [
          generation,
          identity.sessionId,
          identity.userId,
          identity.tenantId,
          identity.companyId,
          identity.siteId,
        ].join(':')
      : `anonymous:${generation}`,
  transition(next: SecurityIdentity | null) {
    generation += 1;
    for (const controller of controllers) controller.abort();
    controllers.clear();
    queryCache.clear();
    identity = next;
    window.dispatchEvent(new Event('businessos:security-transition'));
  },
  track(controller: AbortController) {
    controllers.add(controller);
    return () => controllers.delete(controller);
  },
};
