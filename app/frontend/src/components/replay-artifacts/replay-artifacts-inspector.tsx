import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import type { ReplayArtifactDetail, ReplaySelectionArtifactDay, ReplayCacheBenchmarkOverview, ReplayReasonCount } from '@/services/replay-artifact-api';

function formatOptionalText(value: string | null | undefined): string {
  if (!value) {
    return '--';
  }
  return value;
}

function formatPathLeaf(value: string | null | undefined): string {
  if (!value) {
    return '--';
  }
  const normalized = value.replace(/\\/g, '/');
  const segments = normalized.split('/').filter(Boolean);
  return segments.at(-1) || value;
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

function formatCacheBenchmarkValue(overview: ReplayCacheBenchmarkOverview | undefined): string {
  if (!overview?.requested) {
    return 'not requested';
  }
  return overview.write_status || '--';
}

function formatCacheBenchmarkDescription(overview: ReplayCacheBenchmarkOverview | undefined): string {
  if (!overview?.requested) {
    return '当前 replay 未请求 post-session cache benchmark';
  }
  if (overview.write_status === 'success') {
    const reuse = overview.reuse_confirmed ? 'reuse confirmed' : 'reuse not confirmed';
    const diskGain = overview.disk_hit_gain ?? 0;
    return `${reuse} | disk +${diskGain}`;
  }
  return overview.reason || 'benchmark 未生成';
}

function PathPreviewCard({
  label,
  value,
}: {
  label: string;
  value: string | null | undefined;
}) {
  const displayValue = formatOptionalText(value);
  const leafValue = formatPathLeaf(value);

  return (
    <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-3">
      <p className="text-xs font-medium uppercase tracking-wide text-primary">{label}</p>
      <p className="mt-2 break-all text-sm font-semibold leading-5 text-foreground" title={leafValue}>
        {leafValue}
      </p>
      <p className="mt-2 break-all font-mono text-[11px] leading-5 text-muted-foreground" title={displayValue}>
        {displayValue}
      </p>
    </div>
  );
}

interface ReplayArtifactsInspectorProps {
  detail: ReplayArtifactDetail | null;
  selectionArtifactDetail: ReplaySelectionArtifactDay | null;
  isDetailLoading: boolean;
}

export function ReplayArtifactsInspector({
  detail,
  selectionArtifactDetail,
  isDetailLoading,
}: ReplayArtifactsInspectorProps) {
  if (isDetailLoading || !detail) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Inspector</CardTitle>
          <CardDescription>用于查看当前 report 的运行上下文、cache benchmark 结论和关键 artifact 路径。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="rounded-md border border-border/60 bg-muted/20 p-3">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Report Dir</p>
            <p className="mt-2 break-all font-mono text-[11px] leading-5 text-muted-foreground">{detail.report_dir}</p>
          </div>
          <div className="grid gap-3">
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Cache Benchmark</p>
              <p className="mt-2 text-sm font-semibold text-primary">{formatCacheBenchmarkValue(detail.cache_benchmark_overview)}</p>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">{formatCacheBenchmarkDescription(detail.cache_benchmark_overview)}</p>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Write Status</p>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">
                {Object.entries(detail.selection_artifact_overview.write_status_counts || {}).map(([status, count]) => `${status}:${count}`).join(' | ') || '--'}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {selectionArtifactDetail ? (
        <Card>
          <CardHeader>
            <CardTitle>Trade Date Inspector</CardTitle>
            <CardDescription>当前 trade date 的 snapshot、review 和 feedback artifact 路径。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">{selectionArtifactDetail.trade_date}</Badge>
              <Badge variant="secondary">{selectionArtifactDetail.feedback_summary.feedback_count} feedback</Badge>
            </div>
            <PathPreviewCard label="snapshot" value={selectionArtifactDetail.paths.snapshot_path} />
            <PathPreviewCard label="review" value={selectionArtifactDetail.paths.review_path} />
            <PathPreviewCard label="feedback" value={selectionArtifactDetail.paths.feedback_path} />
          </CardContent>
        </Card>
      ) : null}

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
          <CardDescription>当前摘要对应的底层产物路径与 selection artifact 根目录。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          {Object.entries(detail.artifacts).map(([key, value]) => (
            <PathPreviewCard key={key} label={key} value={String(value)} />
          ))}
          {detail.selection_artifact_overview.artifact_root ? (
            <PathPreviewCard label="selection_artifact_root" value={detail.selection_artifact_overview.artifact_root} />
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}