import { useEffect, useState } from 'react';
import { BarChart3, Clock3, Database, RefreshCw, Wallet } from 'lucide-react';

import {
  replayArtifactApi,
  type ReplayArtifactDetail,
  type ReplayArtifactSummary,
  type ReplayReasonCount,
} from '@/services/replay-artifact-api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '--';
  }
  return `${value.toFixed(2)}%`;
}

function formatRatioPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '--';
  }
  return `${(value * 100).toFixed(2)}%`;
}

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) {
    return '--';
  }
  return value.toFixed(digits);
}

function formatBlockers(blockers: ReplayReasonCount[] | undefined): string {
  if (!blockers || blockers.length === 0) {
    return '--';
  }
  return blockers
    .slice(0, 2)
    .map((item) => `${item.reason} x${item.count}`)
    .join(' | ');
}

function KpiCard({
  title,
  value,
  description,
  icon: Icon,
}: {
  title: string;
  value: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-3">
        <div>
          <CardDescription>{title}</CardDescription>
          <CardTitle className="mt-2 text-2xl">{value}</CardTitle>
        </div>
        <div className="rounded-lg border border-border/60 bg-muted/40 p-2 text-muted-foreground">
          <Icon className="h-4 w-4" />
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-xs text-muted-foreground">{description}</p>
      </CardContent>
    </Card>
  );
}

export function ReplayArtifactsSettings() {
  const [reports, setReports] = useState<ReplayArtifactSummary[]>([]);
  const [selectedReport, setSelectedReport] = useState<string>('');
  const [detail, setDetail] = useState<ReplayArtifactDetail | null>(null);
  const [isListLoading, setIsListLoading] = useState(true);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadReports() {
      setIsListLoading(true);
      setError(null);
      try {
        const items = await replayArtifactApi.list();
        if (cancelled) {
          return;
        }
        setReports(items);
        if (items.length > 0) {
          setSelectedReport((current) => current || items[0].report_dir);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load replay reports');
        }
      } finally {
        if (!cancelled) {
          setIsListLoading(false);
        }
      }
    }

    void loadReports();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedReport) {
      return;
    }

    let cancelled = false;

    async function loadDetail() {
      setIsDetailLoading(true);
      setError(null);
      try {
        const payload = await replayArtifactApi.get(selectedReport);
        if (!cancelled) {
          setDetail(payload);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load replay detail');
          setDetail(null);
        }
      } finally {
        if (!cancelled) {
          setIsDetailLoading(false);
        }
      }
    }

    void loadDetail();

    return () => {
      cancelled = true;
    };
  }, [selectedReport]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-primary">Replay Artifacts</h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
            浏览 long-window replay 的基础绩效、关键 funnel 指标和按 ticker 执行摘要，避免直接翻原始 JSONL。
          </p>
        </div>
        <Button variant="outline" onClick={() => window.location.reload()}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Report Selector</CardTitle>
          <CardDescription>当前接口直接扫描 data/reports 下可识别的 replay summary。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {isListLoading ? (
            <Skeleton className="h-10 w-full" />
          ) : (
            <select
              value={selectedReport}
              onChange={(event) => setSelectedReport(event.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
            >
              {reports.map((report) => (
                <option key={report.report_dir} value={report.report_dir}>
                  {report.report_dir}
                </option>
              ))}
            </select>
          )}
          {error ? <p className="text-sm text-red-500">{error}</p> : null}
        </CardContent>
      </Card>

      {isDetailLoading || !detail ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Skeleton className="h-36" />
          <Skeleton className="h-36" />
          <Skeleton className="h-36" />
          <Skeleton className="h-36" />
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">{detail.window.start_date} .. {detail.window.end_date}</Badge>
            <Badge variant="secondary">{detail.run_header.plan_generation_mode || 'unknown mode'}</Badge>
            <Badge variant="outline">{detail.run_header.model_provider || 'unknown provider'} / {detail.run_header.model_name || 'unknown model'}</Badge>
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              title="Return"
              value={formatPercent(detail.headline_kpi.total_return_pct)}
              description={`Final Value ${formatNumber(detail.headline_kpi.final_value)}`}
              icon={BarChart3}
            />
            <KpiCard
              title="Trade Days / Orders"
              value={`${detail.headline_kpi.executed_trade_days ?? '--'} / ${detail.headline_kpi.total_executed_orders ?? '--'}`}
              description={`Sharpe ${formatNumber(detail.headline_kpi.sharpe_ratio, 3)}`}
              icon={Database}
            />
            <KpiCard
              title="Avg Invested"
              value={formatRatioPercent(detail.deployment_funnel_runtime.avg_invested_ratio)}
              description={`Peak ${formatRatioPercent(detail.deployment_funnel_runtime.peak_invested_ratio)}`}
              icon={Wallet}
            />
            <KpiCard
              title="Avg Day Sec"
              value={formatNumber(detail.deployment_funnel_runtime.avg_total_day_seconds, 2)}
              description={`Post Market ${formatNumber(detail.deployment_funnel_runtime.avg_post_market_seconds, 2)}s`}
              icon={Clock3}
            />
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
            <Card>
              <CardHeader>
                <CardTitle>Ticker Execution Digest</CardTitle>
                <CardDescription>按 ticker 聚合的成交次数、已实现盈亏和持仓质量信号。</CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Ticker</TableHead>
                      <TableHead>Buy / Sell</TableHead>
                      <TableHead>Final</TableHead>
                      <TableHead>Realized</TableHead>
                      <TableHead>Max Float</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {detail.ticker_execution_digest.map((ticker) => (
                      <TableRow key={ticker.ticker}>
                        <TableCell className="font-medium">{ticker.ticker}</TableCell>
                        <TableCell>{ticker.buy_count} / {ticker.sell_count}</TableCell>
                        <TableCell>{ticker.final_long}</TableCell>
                        <TableCell>{formatNumber(ticker.realized_pnl)}</TableCell>
                        <TableCell>{formatPercent(ticker.max_unrealized_pnl_pct * 100)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>

            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle>Funnel Snapshot</CardTitle>
                  <CardDescription>来自 replay 摘要接口的关键漏斗计数与 blocker。</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Avg Layer B</span>
                    <span>{formatNumber(detail.deployment_funnel_runtime.avg_layer_b_count, 2)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Avg Watchlist</span>
                    <span>{formatNumber(detail.deployment_funnel_runtime.avg_watchlist_count, 2)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Avg Buy Orders</span>
                    <span>{formatNumber(detail.deployment_funnel_runtime.avg_buy_order_count, 2)}</span>
                  </div>
                  <div className="space-y-1 pt-2">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Buy blockers</p>
                    <p>{formatBlockers(detail.deployment_funnel_runtime.top_buy_blockers)}</p>
                  </div>
                  <div className="space-y-1 pt-2">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Watch blockers</p>
                    <p>{formatBlockers(detail.deployment_funnel_runtime.top_watchlist_blockers)}</p>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Artifacts</CardTitle>
                  <CardDescription>当前摘要对应的底层产物路径。</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2 text-sm text-muted-foreground">
                  {Object.entries(detail.artifacts).map(([key, value]) => (
                    <div key={key} className="rounded-md border border-border/60 bg-muted/20 px-3 py-2">
                      <p className="font-medium text-primary">{key}</p>
                      <p className="break-all">{value}</p>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}