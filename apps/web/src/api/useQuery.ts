import { useState, useEffect, useCallback, useRef } from 'react';
import { queryCache } from './queryCache';
import { securityContext } from './securityContext';
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
  const { enabled = true, staleTime = 30000 } = options;
  const { scope } = useScope();
  const { session } = useAuth();
  const authorized = Boolean(
    session && scope.tenantId && scope.companyId && session.companyId === scope.companyId
  );
  const scopedKey = `${securityContext.key()}:${key}`;
  const [state, setState] = useState<{
    key: string;
    data: T | undefined;
    loading: boolean;
    error: Error | null;
  }>({ key: scopedKey, data: undefined, loading: true, error: null });
  const latest = useRef(scopedKey);
  const fetcherRef = useRef(fetcher);
  latest.current = scopedKey;
  fetcherRef.current = fetcher;

  const execute = useCallback(async () => {
    if (!enabled || !authorized) return;
    const generation = securityContext.generation();
    setState({ key: scopedKey, data: undefined, loading: true, error: null });
    try {
      const result = await fetcherRef.current();
      if (latest.current !== scopedKey || generation !== securityContext.generation()) return;
      queryCache.set(scopedKey, result);
      setState({ key: scopedKey, data: result, loading: false, error: null });
    } catch (caught) {
      if (latest.current !== scopedKey || generation !== securityContext.generation()) return;
      setState({
        key: scopedKey,
        data: undefined,
        loading: false,
        error: caught instanceof Error ? caught : new Error(String(caught)),
      });
    }
  }, [enabled, authorized, scopedKey]);

  useEffect(() => {
    if (!enabled || !authorized) {
      setState({ key: scopedKey, data: undefined, loading: false, error: null });
      return;
    }
    const cached = queryCache.get<T>(scopedKey, staleTime);
    if (cached !== null) setState({ key: scopedKey, data: cached, loading: false, error: null });
    else void execute();
  }, [scopedKey, staleTime, enabled, authorized, execute]);

  return {
    data: authorized && state.key === scopedKey ? state.data : undefined,
    isLoading:
      authorized && state.key === scopedKey ? state.loading : Boolean(enabled && authorized),
    error: authorized && state.key === scopedKey ? state.error : null,
    refetch: execute,
  };
};
