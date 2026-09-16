import { useState, useEffect, useCallback } from 'react';
import { queryCache } from './queryCache';
import { useScope } from '../scope/ScopeContext';

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
  const { scope } = useScope();

  // Scope cache key by tenant and site to guarantee zero cross-tenant state leakage
  const scopedKey = `${scope.tenantId}:${scope.siteId}:${key}`;

  const [data, setData] = useState<T | undefined>(() => {
    const cached = queryCache.get<T>(scopedKey, staleTime);
    return cached !== null ? cached : initialData;
  });

  const [isLoading, setIsLoading] = useState<boolean>(!data && enabled);
  const [error, setError] = useState<Error | null>(null);

  const execute = useCallback(async () => {
    if (!enabled) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await fetcher();
      queryCache.set(scopedKey, result);
      setData(result);
    } catch (err: any) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setIsLoading(false);
    }
  }, [enabled, scopedKey, fetcher]);

  useEffect(() => {
    const cached = queryCache.get<T>(scopedKey, staleTime);
    if (cached !== null) {
      setData(cached);
      setIsLoading(false);
    } else {
      execute();
    }
  }, [scopedKey, staleTime, execute]);

  return {
    data,
    isLoading,
    error,
    refetch: execute,
  };
};
