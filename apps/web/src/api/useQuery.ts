import { useCallback, useEffect, useMemo, useState } from 'react';
import { queryCache } from './queryCache';
import { useScope } from '../scope/ScopeContext';
import { useAuth } from '../auth/AuthContext';

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
  fetcher: () => Promise<T>,
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

  const execute = useCallback(async () => {
    if (!enabled || !scopedKey) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await fetcher();
      queryCache.set(scopedKey, result);
      setData(result);
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught : new Error(String(caught)));
    } finally {
      setIsLoading(false);
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
  }, [enabled, scopedKey, staleTime, initialData, execute]);

  return { data, isLoading, error, refetch: execute };
};
