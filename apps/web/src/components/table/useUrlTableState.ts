import { useSearchParams } from 'react-router-dom';
import { useMemo, useCallback } from 'react';
import { SortState } from './types';

export interface UrlTableStateOptions {
  defaultPage?: number;
  defaultPageSize?: number;
  defaultSort?: SortState;
}

export const useUrlTableState = (options: UrlTableStateOptions = {}) => {
  const [searchParams, setSearchParams] = useSearchParams();

  const page = useMemo(() => {
    const p = searchParams.get('page');
    return p ? parseInt(p, 10) || 1 : options.defaultPage || 1;
  }, [searchParams, options.defaultPage]);

  const pageSize = useMemo(() => {
    const s = searchParams.get('pageSize');
    return s ? parseInt(s, 10) || 25 : options.defaultPageSize || 25;
  }, [searchParams, options.defaultPageSize]);

  const sort = useMemo<SortState | undefined>(() => {
    const sortBy = searchParams.get('sortBy');
    const sortDir = searchParams.get('sortDir');
    if (sortBy && (sortDir === 'asc' || sortDir === 'desc')) {
      return { columnId: sortBy, direction: sortDir };
    }
    return options.defaultSort;
  }, [searchParams, options.defaultSort]);

  const searchQuery = useMemo(() => {
    return searchParams.get('q') || '';
  }, [searchParams]);

  const setPagination = useCallback(
    (newPage: number, newPageSize: number) => {
      const next = new URLSearchParams(searchParams);
      next.set('page', String(newPage));
      next.set('pageSize', String(newPageSize));
      setSearchParams(next);
    },
    [searchParams, setSearchParams]
  );

  const setSort = useCallback(
    (newSort: SortState) => {
      const next = new URLSearchParams(searchParams);
      next.set('sortBy', newSort.columnId);
      next.set('sortDir', newSort.direction);
      next.set('page', '1'); // reset to first page on sort
      setSearchParams(next);
    },
    [searchParams, setSearchParams]
  );

  const setSearch = useCallback(
    (query: string) => {
      const next = new URLSearchParams(searchParams);
      if (query) {
        next.set('q', query);
      } else {
        next.delete('q');
      }
      next.set('page', '1');
      setSearchParams(next);
    },
    [searchParams, setSearchParams]
  );

  return {
    page,
    pageSize,
    sort,
    searchQuery,
    setPagination,
    setSort,
    setSearch,
  };
};
