/**
 * Cache status API service — fetches cache hit-rate and runtime info.
 */

import { authFetch } from '@/services/auth-api';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface CacheStats {
  lru_hits: number;
  redis_hits: number;
  disk_hits: number;
  misses: number;
  sets: number;
  total_hits: number;
  total_requests: number;
  hit_rate: number;
}

export interface CacheRuntimeInfo {
  lru_maxsize: number;
  redis_available: boolean;
  disk_available: boolean;
  disk_path: string | null;
  disk_entry_count: number;
  disk_file_size_bytes: number;
  stats: CacheStats;
}

export const cacheApi = {
  /**
   * Fetch cache statistics from the backend.
   */
  async getStats(): Promise<CacheRuntimeInfo> {
    const response = await authFetch(`${API_BASE_URL}/cache/stats`);
    if (!response.ok) {
      throw new Error(`Failed to fetch cache stats: ${response.status}`);
    }
    return response.json();
  },
};
