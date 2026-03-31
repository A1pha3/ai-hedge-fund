import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import type {
  ReplayArtifactDetail,
  ReplayBtstControlTowerOverview,
  ReplayBtstControlTowerReference,
  ReplaySelectionArtifactDay,
  ReplayCacheBenchmarkOverview,
  ReplayReasonCount,
  ReplayFeedbackActivity,
  ReplaySelectionArtifactDualTargetOverview,
} from '@/services/replay-artifact-api';

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

function formatCounterMap(values: Record<string, number> | undefined): string {
  if (!values) {
    return '--';
  }
  const entries = Object.entries(values);
  if (entries.length === 0) {
    return '--';
  }
  return entries.map(([key, count]) => `${key}:${count}`).join(' | ');
}

function formatStringList(items: string[] | undefined): string {
  if (!items || items.length === 0) {
    return '--';
  }
  return items.join(' | ');
}

function formatDualTargetOverviewCounts(overview: ReplaySelectionArtifactDualTargetOverview | null | undefined): string {
  if (!overview) {
    return '--';
  }
  return `R ${overview.research_selected_count}/${overview.research_near_miss_count}/${overview.research_rejected_count} | S ${overview.short_trade_selected_count}/${overview.short_trade_near_miss_count}/${overview.short_trade_blocked_count}/${overview.short_trade_rejected_count}`;
}

function formatRepresentativeCases(overview: ReplaySelectionArtifactDualTargetOverview | null | undefined): string {
  if (!overview?.representative_cases || overview.representative_cases.length === 0) {
    return '--';
  }
  return overview.representative_cases
    .slice(0, 3)
    .map((caseItem) => {
      const summary = caseItem.delta_summary?.[0] ? ` | ${caseItem.delta_summary[0]}` : '';
      const tradeDate = caseItem.trade_date ? `${caseItem.trade_date} ` : '';
      return `${tradeDate}${caseItem.ticker}:${caseItem.delta_classification || 'none'}${summary}`;
    })
    .join(' | ');
}

function formatBtstControlTowerReference(reference: ReplayBtstControlTowerReference | null | undefined): string {
  if (!reference) {
    return '--';
  }
  const reportName = formatOptionalText(reference.report_name || formatPathLeaf(reference.report_dir));
  return `${reportName} | ${formatOptionalText(reference.trade_date)} | ${formatOptionalText(reference.selection_target)}`;
}

function formatBtstControlTowerChangeSummary(overview: ReplayBtstControlTowerOverview | null | undefined): string {
  if (!overview) {
    return '--';
  }
  const changedSurfaces = [
    overview.priority_has_changes ? 'priority' : null,
    overview.governance_has_changes ? 'governance' : null,
    overview.replay_has_changes ? 'replay' : null,
  ].filter(Boolean);
  const surfaceSummary = changedSurfaces.length > 0 ? changedSurfaces.join('/') : 'stable';
  return `${formatOptionalText(overview.overall_delta_verdict)} | ${surfaceSummary}`;
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
  feedbackActivity: ReplayFeedbackActivity | null;
  focusedSymbol: string;
  selectedTradeDate: string;
  tradeDateFilterCoverageText: string;
  visibleFeedbackActivityCount: number;
  visibleWorkflowQueueCount: number;
  totalWorkflowQueueCount: number;
  onOpenContext?: (params: { reportName: string; tradeDate: string; symbol: string }) => void;
  isDetailLoading: boolean;
  isActivityLoading: boolean;
  activityError?: string | null;
}

export function ReplayArtifactsInspector({
  detail,
  selectionArtifactDetail,
  feedbackActivity,
  focusedSymbol,
  selectedTradeDate,
  tradeDateFilterCoverageText,
  visibleFeedbackActivityCount,
  visibleWorkflowQueueCount,
  totalWorkflowQueueCount,
  onOpenContext,
  isDetailLoading,
  isActivityLoading,
  activityError,
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

  const dualTargetOverview = detail.selection_artifact_overview.dual_target_overview;
  const btstFollowupOverview = detail.selection_artifact_overview.btst_followup_overview;
  const btstControlTowerOverview = detail.selection_artifact_overview.btst_control_tower_overview;
  const visibleDraftQueue = focusedSymbol === 'all'
    ? (feedbackActivity?.workflow_queue?.draft || [])
    : (feedbackActivity?.workflow_queue?.draft || []).filter((record) => record.symbol === focusedSymbol);
  const visibleRecentRecords = focusedSymbol === 'all'
    ? (feedbackActivity?.recent_records || [])
    : (feedbackActivity?.recent_records || []).filter((record) => record.symbol === focusedSymbol);

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
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Workspace Focus</p>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">trade date {selectedTradeDate || '--'} | symbol {focusedSymbol === 'all' ? '--' : focusedSymbol}</p>
              <p className="mt-1 text-xs leading-6 text-muted-foreground">trade date filter {tradeDateFilterCoverageText}</p>
              <p className="mt-1 text-xs leading-6 text-muted-foreground">activity {visibleFeedbackActivityCount}/{feedbackActivity?.recent_records.length || 0} | queue {visibleWorkflowQueueCount}/{totalWorkflowQueueCount}</p>
            </div>
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
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Dual Target Overview</p>
              <p className="mt-2 text-sm font-semibold text-primary">{dualTargetOverview ? `${dualTargetOverview.dual_target_trade_date_count} dual-target days` : '--'}</p>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">modes {formatCounterMap(dualTargetOverview?.target_mode_counts)}</p>
              <p className="mt-1 text-xs leading-6 text-muted-foreground">counts {formatDualTargetOverviewCounts(dualTargetOverview)}</p>
              <p className="mt-1 text-xs leading-6 text-muted-foreground">delta {formatCounterMap(dualTargetOverview?.delta_classification_counts)}</p>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">BTST Follow-Up</p>
              <p className="mt-2 text-sm font-semibold text-primary">{btstFollowupOverview?.primary_entry_ticker || '--'}</p>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">
                {btstFollowupOverview ? `T ${btstFollowupOverview.trade_date || '--'} -> T+1 ${btstFollowupOverview.next_trade_date || '--'}` : '当前 report 还没有 BTST follow-up 产物'}
              </p>
              <p className="mt-1 text-xs leading-6 text-muted-foreground">
                {btstFollowupOverview ? `watch ${btstFollowupOverview.watchlist_tickers.join(', ') || '--'} | excluded ${btstFollowupOverview.excluded_research_tickers.join(', ') || '--'}` : '--'}
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
          <CardTitle>Feedback Activity</CardTitle>
          <CardDescription>按当前 report 聚合最近 feedback，用于快速判断 backlog 是否还停留在 draft、主要标签集中在哪些语义，以及最近是谁在复核。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {isActivityLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-28 w-full" />
            </div>
          ) : activityError ? (
            <p className="text-sm text-red-500">{activityError}</p>
          ) : feedbackActivity ? (
            <>
              <div className="grid gap-3">
                <div className="rounded-md border border-border/60 bg-muted/20 p-3">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Activity Coverage</p>
                  <p className="mt-2 text-sm font-semibold text-primary">{feedbackActivity.record_count} recent records</p>
                  <p className="mt-2 text-xs leading-6 text-muted-foreground">
                    status {Object.entries(feedbackActivity.review_status_counts || {}).map(([status, count]) => `${status}:${count}`).join(' | ') || '--'}
                  </p>
                </div>
                <div className="rounded-md border border-border/60 bg-muted/20 p-3">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Top Tags</p>
                  <p className="mt-2 text-xs leading-6 text-muted-foreground">
                    {Object.entries(feedbackActivity.tag_counts || {}).slice(0, 4).map(([tag, count]) => `${tag}:${count}`).join(' | ') || '--'}
                  </p>
                </div>
                <div className="rounded-md border border-border/60 bg-muted/20 p-3">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Recent Reviewers</p>
                  <p className="mt-2 text-xs leading-6 text-muted-foreground">
                    {Object.entries(feedbackActivity.reviewer_counts || {}).map(([reviewer, count]) => `${reviewer}:${count}`).join(' | ') || '--'}
                  </p>
                </div>
                <div className="rounded-md border border-border/60 bg-muted/20 p-3">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Workflow Queue</p>
                  <p className="mt-2 text-xs leading-6 text-muted-foreground">
                    {Object.entries(feedbackActivity.workflow_status_counts || {}).map(([status, count]) => `${status}:${count}`).join(' | ') || '--'}
                  </p>
                </div>
              </div>
              <div className="space-y-2">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Pending Draft Queue</p>
                {visibleDraftQueue.length > 0 ? (
                  visibleDraftQueue.slice(0, 5).map((record) => (
                    <div key={`draft-${record.created_at}-${record.symbol}-${record.primary_tag}`} className="rounded-md border border-border/60 bg-background/60 px-3 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{record.trade_date}</Badge>
                        <Badge variant="secondary">{record.symbol}</Badge>
                        <Badge variant="outline">{record.review_scope}</Badge>
                      </div>
                      <p className="mt-2 text-sm font-medium text-primary">{record.primary_tag}</p>
                      <p className="mt-1 text-xs leading-6 text-muted-foreground">{record.reviewer} | {record.created_at}</p>
                      {onOpenContext ? (
                        <div className="mt-3 flex justify-end">
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            onClick={() => onOpenContext({
                              reportName: record.report_name,
                              tradeDate: record.trade_date,
                              symbol: record.symbol,
                            })}
                          >
                            Open Context
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <div className="rounded-md border border-border/60 bg-muted/10 px-3 py-3 text-xs text-muted-foreground">
                    {focusedSymbol === 'all' ? '当前 report 没有待推进的 draft queue。' : '当前 focus symbol 在 draft queue 中没有匹配记录。'}
                  </div>
                )}
              </div>
              <div className="space-y-2">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Latest Records</p>
                {visibleRecentRecords.length > 0 ? (
                  visibleRecentRecords.slice(0, 5).map((record) => (
                    <div key={`${record.created_at}-${record.symbol}-${record.primary_tag}`} className="rounded-md border border-border/60 bg-background/60 px-3 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{record.trade_date}</Badge>
                        <Badge variant="secondary">{record.symbol}</Badge>
                        <Badge variant="outline">{record.review_status}</Badge>
                      </div>
                      <p className="mt-2 text-sm font-medium text-primary">{record.primary_tag}</p>
                      <p className="mt-1 text-xs leading-6 text-muted-foreground">{record.reviewer} | {record.research_verdict} | {record.created_at}</p>
                      <p className="mt-2 text-xs leading-6 text-muted-foreground">{record.notes || '--'}</p>
                      {onOpenContext ? (
                        <div className="mt-3 flex justify-end">
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            onClick={() => onOpenContext({
                              reportName: record.report_name,
                              tradeDate: record.trade_date,
                              symbol: record.symbol,
                            })}
                          >
                            Open Context
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <div className="rounded-md border border-border/60 bg-muted/10 px-3 py-3 text-xs text-muted-foreground">
                    {focusedSymbol === 'all' ? '当前 report 还没有可展示的 feedback activity。' : '当前 focus symbol 没有匹配的 recent activity。'}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="rounded-md border border-border/60 bg-muted/10 px-3 py-3 text-xs text-muted-foreground">
              当前 report 还没有可展示的 feedback activity。
            </div>
          )}
        </CardContent>
      </Card>

      {dualTargetOverview ? (
        <Card>
          <CardHeader>
            <CardTitle>Dual Target Inspector</CardTitle>
            <CardDescription>报告级双目标聚合，让研究员在点进具体 trade date 之前先看到 target mode 分布、delta 聚类和代表性案例。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Target Modes</p>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">{formatCounterMap(dualTargetOverview.target_mode_counts)}</p>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Aggregated Decisions</p>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">{formatDualTargetOverviewCounts(dualTargetOverview)}</p>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Dominant Delta Reasons</p>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">{formatStringList(dualTargetOverview.dominant_delta_reasons)}</p>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Representative Cases</p>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">{formatRepresentativeCases(dualTargetOverview)}</p>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {btstFollowupOverview ? (
        <Card>
          <CardHeader>
            <CardTitle>BTST Follow-Up</CardTitle>
            <CardDescription>报告级次日简报与盘前执行卡摘要，便于在进入 trade date 细节前快速确认主票、观察票和明确非交易票。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Primary Entry</p>
              <p className="mt-2 text-sm font-semibold text-primary">{btstFollowupOverview.primary_entry_ticker || '--'}</p>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">selection_target {btstFollowupOverview.selection_target || '--'}</p>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Watchlist</p>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">{btstFollowupOverview.watchlist_tickers.join(', ') || '--'}</p>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Explicit Non-Trades</p>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">{btstFollowupOverview.excluded_research_tickers.join(', ') || '--'}</p>
            </div>
            {Object.entries(btstFollowupOverview.artifacts || {}).map(([key, value]) => (
              <PathPreviewCard key={key} label={key} value={String(value)} />
            ))}
          </CardContent>
        </Card>
      ) : null}

      {btstControlTowerOverview ? (
        <Card>
          <CardHeader>
            <CardTitle>BTST Control Tower</CardTitle>
            <CardDescription>压缩展示最新 open-ready delta、nightly 状态和关键 operator focus，值班时不用再手动翻 reports 目录。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Delta Verdict</p>
              <p className="mt-2 text-sm font-semibold text-primary">{formatBtstControlTowerChangeSummary(btstControlTowerOverview)}</p>
              <p className="mt-1 text-xs leading-6 text-muted-foreground">comparison {formatOptionalText(btstControlTowerOverview.comparison_basis)}</p>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Current Latest</p>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">{formatBtstControlTowerReference(btstControlTowerOverview.current_reference)}</p>
              <p className="mt-1 text-xs leading-6 text-muted-foreground">{btstControlTowerOverview.selected_report_matches_current_reference ? 'selected report matches latest BTST run' : 'selected report differs from latest BTST run'}</p>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Governance</p>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">{formatOptionalText(btstControlTowerOverview.governance_overall_verdict)} | waiting {btstControlTowerOverview.waiting_lane_count ?? '--'} | ready {btstControlTowerOverview.ready_lane_count ?? '--'}</p>
              <p className="mt-1 text-xs leading-6 text-muted-foreground">lanes {formatCounterMap(btstControlTowerOverview.lane_status_counts)}</p>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Operator Focus</p>
              <div className="mt-2 space-y-2 text-xs leading-6 text-muted-foreground">
                {(btstControlTowerOverview.operator_focus.length > 0 ? btstControlTowerOverview.operator_focus : [btstControlTowerOverview.recommendation || '--']).map((item, index) => (
                  <p key={`btst-control-focus-${index}`}>{item}</p>
                ))}
              </div>
            </div>
            {Object.entries(btstControlTowerOverview.artifacts).map(([key, value]) => (
              <PathPreviewCard key={`btst-control-artifact-${key}`} label={key} value={value} />
            ))}
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