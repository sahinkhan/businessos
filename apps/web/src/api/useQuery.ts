import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { queryCache } from './queryCache';
import { useScope } from '../scope/ScopeContext';
import { useAuth } from '../auth/AuthContext';
import { securityContext } from './securityContext';

export interface UseQueryOptions<T> {
  enabled?: boolean;
  staleTime?: number;
  initialData?: T;
}

export interface UseQueryResult<T> {
  data: T | undefined;
  isLoading: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
}

export const useQuery = <T>(
  key: string,
  fetcher: (signal?: AbortSignal) => Promise<T>,
  options: UseQueryOptions<T> = {}
): UseQueryResult<T> => {
  const { enabled = true, staleTime = 30000, initialData } = options;
  const { user, isAuthenticated } = useAuth();
  const { scope, status } = useScope();
  const trustedContext = Boolean(isAuthenticated && user && scope && status === 'ready');

  const scopedKey = useMemo(
    () =>
      trustedContext && user && scope
        ? [
            user.id,
            scope.tenantId,
            scope.legalEntityId ?? '',
            scope.companyId,
            scope.siteId,
            key,
          ].join(':')
        : null,
    [trustedContext, user, scope, key]
  );

  const [data, setData] = useState<T | undefined>(initialData);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const requestSequence = useRef(0);
  const activeController = useRef<AbortController | null>(null);

  const execute = useCallback(async () => {
    if (!enabled || !scopedKey) return;
    activeController.current?.abort();
    const controller = securityContext.createAbortController();
    activeController.current = controller;
    const sequence = ++requestSequence.current;
    const generation = securityContext.generation();
    const isCurrent = () =>
      !controller.signal.aborted &&
      sequence === requestSequence.current &&
      generation === securityContext.generation();
    setIsLoading(true);
    setError(null);
    try {
      const result = await fetcher(controller.signal);
      if (!isCurrent()) return;
      queryCache.set(scopedKey, result);
      setData(result);
    } catch (caught: unknown) {
      if (!isCurrent()) return;
      setError(caught instanceof Error ? caught : new Error(String(caught)));
    } finally {
      securityContext.release(controller);
      if (isCurrent()) setIsLoading(false);
    }
  }, [enabled, scopedKey, fetcher]);

  useEffect(() => {
    if (!enabled || !scopedKey) {
      setData(initialData);
      setIsLoading(false);
      return;
    }
    const cached = queryCache.get<T>(scopedKey, staleTime);
    if (cached !== null) {
      setData(cached);
      setIsLoading(false);
      return;
    }
    void execute();
    return () => {
      requestSequence.current += 1;
      activeController.current?.abort();
      activeController.current = null;
    };
  }, [enabled, scopedKey, staleTime, initialData, execute]);

  return { data, isLoading, error, refetch: execute };
};
