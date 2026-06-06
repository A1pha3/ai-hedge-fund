import { useEffect, useState } from 'react';
import { AlertTriangle, BarChart3, Loader2, TrendingDown, TrendingUp } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  type LookbackAuditResponse,
  type TickerAuditResult,
  fetchLookbackAudit,
} from '@/services/lookback-audit-api';

interface LookbackAuditPanelProps {
  /** Default audit date (the trade date to look back at). */
  defaultDate?: string;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoIso(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

function formatPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}%`;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '--';
  return iso;
}

function returnColor(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'text-muted-foreground';
  if (value > 0) return 'text-green-500';
  return 'text-red-500';
}

function hitRateBadge(rate: number | undefined) {
  if (rate === undefined) return <Badge variant="outline">--</Badge>;
  if (rate >= 0.6) return <Badge variant="success">{Math.round(rate * 100)}% hit</Badge>;
  if (rate >= 0.4) return <Badge variant="warning">{Math.round(rate * 100)}% hit</Badge>;
  return <Badge variant="destructive">{Math.round(rate * 100)}% hit</Badge>;
}

function dataStatusBadge(status: string) {
  const variant =
    status === 'ok' ? 'success' : status === 'partial' ? 'warning' : 'destructive';
  return <Badge variant={variant}>{status}</Badge>;
}

interface TickerRowProps {
  row: TickerAuditResult;
}

function TickerRow({ row }: TickerRowProps) {
  return (
    <TableRow data-testid="lookback-ticker-row" data-ticker={row.ticker}>
      <TableCell className="font-mono">{row.ticker}</TableCell>
      <TableCell className="text-right">{row.rank}</TableCell>
      <TableCell className="text-right">
        {row.score_final !== null && row.score_final !== undefined
          ? row.score_final.toFixed(3)
          : '--'}
      </TableCell>
      <TableCell>{formatDate(row.entry_date)}</TableCell>
      <TableCell className="text-right">
        {row.entry_price !== null && row.entry_price !== undefined
          ? row.entry_price.toFixed(2)
          : '--'}
      </TableCell>
      <TableCell className="text-right">
        {row.exit_price !== null && row.exit_price !== undefined
          ? row.exit_price.toFixed(2)
          : '--'}
      </TableCell>
      <TableCell
        data-testid="lookback-return"
        className={`text-right font-medium ${returnColor(row.return_pct)}`}
      >
        {formatPct(row.return_pct)}
      </TableCell>
      <TableCell className={`text-right ${returnColor(row.max_return_pct)}`}>
        {formatPct(row.max_return_pct)}
      </TableCell>
      <TableCell className={`text-right ${returnColor(row.max_drawdown_pct)}`}>
        {formatPct(row.max_drawdown_pct)}
      </TableCell>
      <TableCell>{dataStatusBadge(row.data_status)}</TableCell>
    </TableRow>
  );
}

export function LookbackAuditPanel({ defaultDate }: LookbackAuditPanelProps) {
  const initialDate = defaultDate ?? daysAgoIso(30);
  const [auditDate, setAuditDate] = useState<string>(initialDate);
  const [days, setDays] = useState<number>(30);
  const [topN, setTopN] = useState<number>(10);
  const [data, setData] = useState<LookbackAuditResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  const reload = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchLookbackAudit({ date: auditDate, days, topN });
      setData(res);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Auto-load on mount with the default date; subsequent reloads are
    // triggered explicitly by the user clicking "Run audit".
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const summary = data?.summary ?? {};
  const tickerResults = data?.ticker_results ?? [];
  const hitRate = summary.hit_rate as number | undefined;
  const avgReturn = summary.avg_return_pct as number | undefined;

  return (
    <Card data-testid="lookback-audit-panel">
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2 text-lg">
              <BarChart3 className="h-5 w-5" />
              30-Day Lookback Audit
            </CardTitle>
            <CardDescription>
              对历史某日的选股结果做 N 日回看 ——
              看看"过去 30 天我们选出的 top 票"实际涨跌如何。
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Controls */}
        <div className="flex flex-wrap items-end gap-3" data-testid="lookback-controls">
          <div className="flex flex-col gap-1">
            <label htmlFor="lookback-date" className="text-xs text-muted-foreground">
              审计日期 (audit date)
            </label>
            <Input
              id="lookback-date"
              data-testid="lookback-date-input"
              type="date"
              value={auditDate}
              max={todayIso()}
              onChange={(e) => setAuditDate(e.target.value)}
              className="w-[180px]"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="lookback-days" className="text-xs text-muted-foreground">
              前瞻天数 (days)
            </label>
            <Input
              id="lookback-days"
              data-testid="lookback-days-input"
              type="number"
              min={1}
              max={365}
              value={days}
              onChange={(e) => setDays(Math.max(1, Math.min(365, Number(e.target.value) || 30)))}
              className="w-[100px]"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="lookback-topn" className="text-xs text-muted-foreground">
              Top N
            </label>
            <Input
              id="lookback-topn"
              data-testid="lookback-topn-input"
              type="number"
              min={1}
              max={50}
              value={topN}
              onChange={(e) => setTopN(Math.max(1, Math.min(50, Number(e.target.value) || 10)))}
              className="w-[80px]"
            />
          </div>
          <Button
            data-testid="lookback-run-button"
            onClick={() => void reload()}
            disabled={loading}
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Run audit'}
          </Button>
        </div>

        {/* Error state */}
        {error && (
          <div
            data-testid="lookback-error"
            className="flex items-start gap-2 rounded-md border border-red-500/40 bg-red-50/40 px-3 py-2 text-sm text-red-700 dark:bg-red-950/30 dark:text-red-200"
          >
            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Loading skeleton */}
        {loading && !data && (
          <div className="space-y-2" data-testid="lookback-skeleton">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        )}

        {/* Data state */}
        {data && !error && (
          <div className="space-y-4">
            {/* Headline summary */}
            <div
              data-testid="lookback-headline"
              className="grid grid-cols-2 gap-3 sm:grid-cols-4"
            >
              <div className="rounded-md border border-border/40 bg-muted/20 px-3 py-2">
                <p className="text-xs text-muted-foreground">Selected</p>
                <p className="text-lg font-semibold">{data.selected_count}</p>
              </div>
              <div className="rounded-md border border-border/40 bg-muted/20 px-3 py-2">
                <p className="text-xs text-muted-foreground">Audited</p>
                <p className="text-lg font-semibold">{data.audited_count}</p>
              </div>
              <div className="rounded-md border border-border/40 bg-muted/20 px-3 py-2">
                <p className="text-xs text-muted-foreground">Hit Rate</p>
                <div data-testid="lookback-hit-rate">{hitRateBadge(hitRate)}</div>
              </div>
              <div className="rounded-md border border-border/40 bg-muted/20 px-3 py-2">
                <p className="text-xs text-muted-foreground">Avg Return</p>
                <p
                  className={`text-lg font-semibold ${returnColor(avgReturn)}`}
                  data-testid="lookback-avg-return"
                >
                  {formatPct(avgReturn)}
                </p>
              </div>
            </div>

            {/* Best/Worst/Median callouts */}
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="inline-flex items-center gap-1 text-green-500">
                <TrendingUp className="h-4 w-4" /> best {formatPct(summary.best_return_pct as number | undefined)}
              </span>
              <span className="inline-flex items-center gap-1 text-red-500">
                <TrendingDown className="h-4 w-4" /> worst {formatPct(summary.worst_return_pct as number | undefined)}
              </span>
              <span className="inline-flex items-center gap-1 text-muted-foreground">
                median {formatPct(summary.median_return_pct as number | undefined)}
              </span>
            </div>

            {/* Per-ticker table */}
            {tickerResults.length > 0 ? (
              <Table data-testid="lookback-ticker-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>Ticker</TableHead>
                    <TableHead className="text-right">Rank</TableHead>
                    <TableHead className="text-right">Score</TableHead>
                    <TableHead>Entry Date</TableHead>
                    <TableHead className="text-right">Entry</TableHead>
                    <TableHead className="text-right">Exit</TableHead>
                    <TableHead className="text-right">Return</TableHead>
                    <TableHead className="text-right">Max Up</TableHead>
                    <TableHead className="text-right">Max DD</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tickerResults.map((row) => (
                    <TickerRow key={row.ticker} row={row} />
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div
                data-testid="lookback-empty"
                className="rounded-md border border-border/40 bg-muted/20 px-3 py-6 text-center text-sm text-muted-foreground"
              >
                该日期没有可审计的选股结果。
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
