interface CacheEntry<T> {
  data: T;
  timestamp: number;
}

class QueryCache {
  private cache = new Map<string, CacheEntry<any>>();

  public get<T>(key: string, maxAgeMs: number = 30000): T | null {
    const entry = this.cache.get(key);
    if (!entry) return null;
    if (Date.now() - entry.timestamp > maxAgeMs) {
      this.cache.delete(key);
      return null;
    }
    return entry.data;
  }

  public set<T>(key: string, data: T): void {
    this.cache.set(key, { data, timestamp: Date.now() });
  }

  public invalidate(keyPrefix: string): void {
    for (const k of this.cache.keys()) {
      if (k.startsWith(keyPrefix)) {
        this.cache.delete(k);
      }
    }
  }

  public clear(): void {
    this.cache.clear();
  }
}

export const queryCache = new QueryCache();
