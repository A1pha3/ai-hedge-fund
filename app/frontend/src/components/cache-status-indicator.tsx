import { Badge } from '@/components/ui/badge';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cacheApi, type CacheRuntimeInfo } from '@/services/cache-api';
import { cn } from '@/lib/utils';
import { Database, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function hitRateColor(rate: number): string {
  if (rate >= 0.8) return 'text-green-400';
  if (rate >= 0.5) return 'text-yellow-400';
  return 'text-red-400';
}

function hitRateBg(rate: number): string {
  if (rate >= 0.8) return 'bg-green-500/15 border-green-500/30';
  if (rate >= 0.5) return 'bg-yellow-500/15 border-yellow-500/30';
  return 'bg-red-500/15 border-red-500/30';
}

export function CacheStatusIndicator() {
  const [info, setInfo] = useState<CacheRuntimeInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  const fetchStats = useCallback(async () => {
    setLoading(true);
    try {
      const data = await cacheApi.getStats();
      setInfo(data);
    } catch {
      // Silently fail — this is a non-critical UI element
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch on mount and when popover opens
  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  useEffect(() => {
    if (open) fetchStats();
  }, [open, fetchStats]);

  const hitRate = info?.stats?.hit_rate ?? 0;
  const hitPercent = Math.round(hitRate * 100);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          className={cn(
            'inline-flex items-center gap-1.5 px-2 py-1 rounded-md border text-xs font-medium transition-colors',
            'hover:bg-ramp-grey-700 cursor-pointer',
            hitRateBg(hitRate),
          )}
          aria-label={`Cache hit rate: ${hitPercent}%`}
        >
          <Database size={12} />
          <span className={cn('font-mono', hitRateColor(hitRate))}>
            {info ? `${hitPercent}%` : '...'}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={8}
        className="w-72 p-0 bg-popover border-border"
      >
        <div className="p-3 border-b border-border">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold">Cache Status</h4>
            <button
              onClick={fetchStats}
              disabled={loading}
              className="p-1 rounded hover:bg-ramp-grey-700 transition-colors"
              aria-label="Refresh cache stats"
            >
              <RefreshCw size={12} className={cn(loading && 'animate-spin')} />
            </button>
          </div>
        </div>

        {info ? (
          <div className="p-3 space-y-3 text-xs">
            {/* Hit rate */}
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Hit Rate</span>
              <span className={cn('font-mono font-bold text-sm', hitRateColor(hitRate))}>
                {hitPercent}%
              </span>
            </div>

            {/* Stats breakdown */}
            <div className="space-y-1.5 text-muted-foreground">
              <div className="flex justify-between">
                <span>LRU hits</span>
                <span className="font-mono text-foreground">{info.stats.lru_hits}</span>
              </div>
              <div className="flex justify-between">
                <span>Redis hits</span>
                <span className="font-mono text-foreground">{info.stats.redis_hits}</span>
              </div>
              <div className="flex justify-between">
                <span>Disk hits</span>
                <span className="font-mono text-foreground">{info.stats.disk_hits}</span>
              </div>
              <div className="flex justify-between">
                <span>Misses</span>
                <span className="font-mono text-foreground">{info.stats.misses}</span>
              </div>
              <div className="flex justify-between">
                <span>Total requests</span>
                <span className="font-mono text-foreground">{info.stats.total_requests}</span>
              </div>
            </div>

            {/* Divider */}
            <div className="border-t border-border" />

            {/* Cache layers */}
            <div className="space-y-1.5 text-muted-foreground">
              <div className="flex justify-between items-center">
                <span>LRU max size</span>
                <span className="font-mono text-foreground">{info.lru_maxsize}</span>
              </div>
              <div className="flex justify-between items-center">
                <span>Redis</span>
                <Badge variant={info.redis_available ? 'success' : 'secondary'} className="text-[10px] px-1.5 py-0">
                  {info.redis_available ? 'ON' : 'OFF'}
                </Badge>
              </div>
              <div className="flex justify-between items-center">
                <span>Disk</span>
                <Badge variant={info.disk_available ? 'success' : 'secondary'} className="text-[10px] px-1.5 py-0">
                  {info.disk_available ? 'ON' : 'OFF'}
                </Badge>
              </div>
              {info.disk_available && (
                <>
                  <div className="flex justify-between">
                    <span>Disk entries</span>
                    <span className="font-mono text-foreground">{info.disk_entry_count}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Disk size</span>
                    <span className="font-mono text-foreground">
                      {formatBytes(info.disk_file_size_bytes)}
                    </span>
                  </div>
                </>
              )}
            </div>
          </div>
        ) : (
          <div className="p-3 text-xs text-muted-foreground text-center">
            {loading ? 'Loading...' : 'Unable to fetch cache stats'}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
