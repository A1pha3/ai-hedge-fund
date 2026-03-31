import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Skeleton } from '@/components/ui/skeleton';
import type {
  ReplayArtifactDetail,
  ReplayBtstControlTowerLaneRow,
  ReplayBtstControlTowerOverview,
  ReplayBtstControlTowerReference,
  ReplayBtstReplayContextReference,
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

const BTST_TOKEN_LABELS: Record<string, string> = {
  stable: '稳定',
  changed: '有变化',
  priority: '优先级',
  governance: '治理',
  replay: '回放',
  nightly_history: '夜间历史对照',
  short_trade_only: '短线专用',
  governance_ready: '治理就绪',
  governance_waiting: '等待治理',
  waiting: '等待中',
  ready: '已就绪',
  active: '进行中',
  blocked: '已阻塞',
  primary: '主车道',
  shadow: '影子车道',
  recurring: '复发车道',
  structural: '结构车道',
  candidate_entry_shadow_refresh: '候选入场影子刷新',
  btst_governance_synthesis_refresh: '治理综合刷新',
  btst_governance_validation_refresh: '治理验证刷新',
  btst_replay_cohort_refresh: '回放队列刷新',
  success: '成功',
  missing: '缺失',
  skipped: '跳过',
  no_change: '无变化',
  cross_window_stability_missing: '跨窗口稳定性不足',
  same_rule_shadow_expansion_not_ready: '同规则影子扩展未就绪',
  post_release_quality_negative: '放量后质量转负',
  blocked_by_single_window_candidate_entry_signal: '被单窗口候选入场信号阻塞',
  broad_penalty_relief: '广义 stale/extension 惩罚放松',
  broad_penalty_route_closed_current_window: '当前窗口已关闭',
};

const BTST_ARTIFACT_LABELS: Record<string, string> = {
  open_ready_delta_json: '开盘前差分 JSON',
  open_ready_delta_markdown: '开盘前差分 Markdown',
  nightly_control_tower_json: '夜间控制塔 JSON',
  nightly_control_tower_markdown: '夜间控制塔 Markdown',
  report_manifest_json: '报告清单 JSON',
  replay_cohort_json: '回放队列 JSON',
  replay_cohort_markdown: '回放队列 Markdown',
};

function formatBtstToken(value: string | null | undefined): string {
  if (!value) {
    return '--';
  }
  return BTST_TOKEN_LABELS[value] || value.replace(/_/g, ' ');
}

function formatBtstArtifactLabel(value: string): string {
  return BTST_ARTIFACT_LABELS[value] || value.replace(/_/g, ' ');
}

function formatBtstEvidenceHighlight(value: string): string {
  const replacements: Array<[string, string]> = [
    ['missing windows', '缺失窗口'],
    ['close+ rate', '收盘上涨率'],
    ['close mean', '收盘均值'],
    ['high mean', '盘中高点均值'],
    ['same-rule peers', '同规则样本'],
    ['blocked cases', '阻塞样本'],
    ['threshold-only', '仅阈值'],
    ['freeze', '冻结'],
    ['locality', '局部性'],
    ['rescuable', '可救援'],
    ['cases', '样本'],
    ['windows', '窗口'],
  ];

  return replacements.reduce((current, [source, target]) => current.split(source).join(target), value);
}

function formatBtstCounterMap(values: Record<string, number> | undefined): string {
  if (!values) {
    return '--';
  }
  const entries = Object.entries(values);
  if (entries.length === 0) {
    return '--';
  }
  return entries.map(([key, count]) => `${formatBtstToken(key)} ${count}`).join(' | ');
}

function formatBtstRefreshSummary(values: Record<string, string> | undefined): string {
  if (!values) {
    return '--';
  }
  const entries = Object.values(values);
  if (entries.length === 0) {
    return '--';
  }
  const translated = entries.map((value) => formatBtstToken(value));
  const unique = Array.from(new Set(translated));
  return unique.join(' / ');
}

function formatBtstReferenceCompactName(reference: ReplayBtstControlTowerReference | null | undefined): string {
  if (!reference) {
    return '--';
  }
  return formatPathLeaf(reference.report_name || reference.report_dir);
}

function isSameBtstReference(
  current: ReplayBtstControlTowerReference | null | undefined,
  previous: ReplayBtstControlTowerReference | null | undefined,
): boolean {
  if (!current || !previous) {
    return false;
  }
  return current.report_name === previous.report_name
    && current.report_dir === previous.report_dir
    && current.trade_date === previous.trade_date
    && current.selection_target === previous.selection_target;
}

function formatBtstControlTowerReference(reference: ReplayBtstControlTowerReference | null | undefined): string {
  if (!reference) {
    return '--';
  }
  const reportName = formatOptionalText(reference.report_name || formatPathLeaf(reference.report_dir));
  return `${reportName} | ${formatOptionalText(reference.trade_date)} | ${formatBtstToken(reference.selection_target)}`;
}

function formatBtstControlTowerChangeSummary(overview: ReplayBtstControlTowerOverview | null | undefined): string {
  if (!overview) {
    return '--';
  }
  const changedSurfaces = [
    overview.priority_has_changes ? '优先级' : null,
    overview.governance_has_changes ? '治理' : null,
    overview.replay_has_changes ? '回放' : null,
  ].filter(Boolean);
  const surfaceSummary = changedSurfaces.length > 0 ? changedSurfaces.join('/') : '无结构变化';
  return `${formatBtstToken(overview.overall_delta_verdict)} | ${surfaceSummary}`;
}

function formatBtstControlTowerLaneEvidence(lane: ReplayBtstControlTowerLaneRow | null | undefined): string {
  if (!lane || lane.evidence_highlights.length === 0) {
    return '--';
  }
  return lane.evidence_highlights.map((item) => formatBtstEvidenceHighlight(item)).join(' | ');
}

function buildReplayContextParams(
  reference: ReplayBtstControlTowerReference | ReplayBtstReplayContextReference | null | undefined,
  fallbackSymbol = 'all',
): { reportName: string; tradeDate: string; symbol: string } | null {
  if (!reference?.report_name || !reference.trade_date) {
    return null;
  }
  const symbol = 'symbol' in reference && typeof reference.symbol === 'string' && reference.symbol
    ? reference.symbol
    : fallbackSymbol;
  return {
    reportName: reference.report_name,
    tradeDate: reference.trade_date,
    symbol,
  };
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

function BtstReferenceSnapshot({
  label,
  reference,
  summary,
  actionLabel,
  actionAriaLabel,
  onOpen,
}: {
  label: string;
  reference: ReplayBtstControlTowerReference | null | undefined;
  summary: string;
  actionLabel?: string;
  actionAriaLabel?: string;
  onOpen?: (() => void) | null;
}) {
  if (!reference) {
    return (
      <div className="rounded-lg border border-border/60 bg-background/60 px-3 py-3">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
        <p className="mt-2 text-sm font-medium text-muted-foreground">--</p>
      </div>
    );
  }

  const fullReference = formatBtstControlTowerReference(reference);

  return (
    <div className="rounded-lg border border-border/60 bg-background/60 px-3 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge variant="secondary">{formatOptionalText(reference.trade_date)}</Badge>
            <Badge variant="outline">{formatBtstToken(reference.selection_target)}</Badge>
          </div>
          <p className="mt-2 truncate text-sm font-semibold text-primary" title={fullReference}>{formatBtstReferenceCompactName(reference)}</p>
          <p className="mt-1 text-xs leading-6 text-muted-foreground">{summary}</p>
        </div>
        <Popover>
          <PopoverTrigger asChild>
            <Button type="button" variant="ghost" size="sm" className="h-8 px-2 text-xs">
              详情
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-80 space-y-2">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">完整引用</p>
              <p className="mt-2 break-all text-sm leading-6 text-foreground">{fullReference}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">报告目录</p>
              <p className="mt-2 break-all font-mono text-[11px] leading-5 text-muted-foreground">{formatOptionalText(reference.report_dir)}</p>
            </div>
          </PopoverContent>
        </Popover>
      </div>
      {actionLabel && onOpen ? (
        <div className="mt-3 flex justify-end">
          <Button type="button" variant="outline" size="sm" aria-label={actionAriaLabel || actionLabel} onClick={onOpen}>
            {actionLabel}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function BtstArtifactSummaryPopover({
  artifacts,
}: {
  artifacts: Record<string, string | null | undefined> | undefined;
}) {
  const entries = Object.entries(artifacts || {}).filter(([, value]) => Boolean(value));
  if (entries.length === 0) {
    return null;
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" size="sm" className="h-8 px-2 text-xs">
          查看产物
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 space-y-3">
        {entries.map(([key, value]) => (
          <div key={`artifact-${key}`} className="rounded-lg border border-border/50 bg-background/60 px-3 py-3">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">{formatBtstArtifactLabel(key)}</p>
            <p className="mt-2 break-all font-mono text-[11px] leading-5 text-muted-foreground">{formatOptionalText(value)}</p>
          </div>
        ))}
      </PopoverContent>
    </Popover>
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
            <CardTitle>BTST 控制塔</CardTitle>
            <CardDescription>压缩展示最新差分、夜间治理和关键值班信息，避免在 inspector 里再看到一整串超长 report 引用。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">变化结论</p>
              <p className="mt-2 text-sm font-semibold text-primary">{formatBtstControlTowerChangeSummary(btstControlTowerOverview)}</p>
              <p className="mt-1 text-xs leading-6 text-muted-foreground">对比基准：{formatBtstToken(btstControlTowerOverview.comparison_basis)}</p>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">治理状态</p>
              <p className="mt-2 text-sm font-semibold text-primary">{formatBtstToken(btstControlTowerOverview.governance_overall_verdict)}</p>
              <p className="mt-1 text-xs leading-6 text-muted-foreground">等待 {btstControlTowerOverview.waiting_lane_count ?? '--'} 条 | 就绪 {btstControlTowerOverview.ready_lane_count ?? '--'} 条</p>
              <p className="mt-1 text-xs leading-6 text-muted-foreground">车道分布：{formatBtstCounterMap(btstControlTowerOverview.lane_status_counts)}</p>
              <p className="mt-1 text-xs leading-6 text-muted-foreground">刷新概览：{formatBtstRefreshSummary(btstControlTowerOverview.refresh_status)}</p>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 p-3 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">当前与对照运行</p>
                <Badge variant={btstControlTowerOverview.selected_report_matches_current_reference ? 'secondary' : 'outline'}>
                  {btstControlTowerOverview.selected_report_matches_current_reference ? '当前报告已对齐最新运行' : '当前报告不是最新运行'}
                </Badge>
              </div>
              <div className="grid gap-3">
                <BtstReferenceSnapshot
                  label="当前运行"
                  reference={btstControlTowerOverview.current_reference}
                  summary={btstControlTowerOverview.selected_report_matches_current_reference ? '当前 inspector 已对齐最新 BTST 运行。' : '建议先打开当前运行，再检查车道和动作。'}
                  actionLabel={onOpenContext && buildReplayContextParams(btstControlTowerOverview.current_reference) ? '打开当前' : undefined}
                  actionAriaLabel="打开当前 BTST 运行"
                  onOpen={onOpenContext && buildReplayContextParams(btstControlTowerOverview.current_reference)
                    ? () => {
                        const params = buildReplayContextParams(btstControlTowerOverview.current_reference);
                        if (params) {
                          onOpenContext(params);
                        }
                      }
                    : null}
                />
                <BtstReferenceSnapshot
                  label="上一轮对照"
                  reference={btstControlTowerOverview.previous_reference}
                  summary={isSameBtstReference(btstControlTowerOverview.current_reference, btstControlTowerOverview.previous_reference)
                    ? '上一轮与当前一致，本轮属于稳定复跑。'
                    : '用于判断本轮是否切换了运行基线。'}
                  actionLabel={onOpenContext && buildReplayContextParams(btstControlTowerOverview.previous_reference) && !isSameBtstReference(btstControlTowerOverview.current_reference, btstControlTowerOverview.previous_reference) ? '打开上一轮' : undefined}
                  actionAriaLabel="打开上一轮 BTST 运行"
                  onOpen={onOpenContext && buildReplayContextParams(btstControlTowerOverview.previous_reference) && !isSameBtstReference(btstControlTowerOverview.current_reference, btstControlTowerOverview.previous_reference)
                    ? () => {
                        const params = buildReplayContextParams(btstControlTowerOverview.previous_reference);
                        if (params) {
                          onOpenContext(params);
                        }
                      }
                    : null}
                />
              </div>
              <div className="flex flex-wrap gap-2">
                <Popover>
                  <PopoverTrigger asChild>
                    <Button type="button" variant="ghost" size="sm" className="h-8 px-2 text-xs">
                      刷新明细
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent align="end" className="w-80 space-y-3">
                    {Object.entries(btstControlTowerOverview.refresh_status).map(([key, value]) => (
                      <div key={`btst-inspector-refresh-${key}`} className="rounded-lg border border-border/50 bg-background/60 px-3 py-3">
                        <p className="text-xs uppercase tracking-wide text-muted-foreground">{formatBtstToken(key)}</p>
                        <p className="mt-2 text-sm font-medium text-foreground">{formatBtstToken(value)}</p>
                      </div>
                    ))}
                  </PopoverContent>
                </Popover>
                <BtstArtifactSummaryPopover artifacts={btstControlTowerOverview.artifacts} />
              </div>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">值班关注</p>
              <div className="mt-2 space-y-2 text-xs leading-6 text-muted-foreground">
                {(btstControlTowerOverview.operator_focus.length > 0 ? btstControlTowerOverview.operator_focus : [btstControlTowerOverview.recommendation || '--']).map((item, index) => (
                  <p key={`btst-control-focus-${index}`}>{item}</p>
                ))}
              </div>
            </div>
            {btstControlTowerOverview.closed_frontiers && btstControlTowerOverview.closed_frontiers.length > 0 ? (
              <div className="rounded-md border border-border/60 bg-muted/20 p-3 space-y-2">
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">已关闭路线</p>
                  <p className="mt-1 text-xs leading-6 text-muted-foreground">明确哪些 broad rollout route 已被当前窗口关闭。</p>
                </div>
                {btstControlTowerOverview.closed_frontiers.map((frontier) => (
                  <div key={`${frontier.frontier_id || 'frontier'}-${frontier.status || 'status'}`} className="rounded-md border border-border/50 bg-background/60 px-3 py-3">
                    <div className="flex flex-wrap gap-2">
                      <Badge variant="secondary">{formatBtstToken(frontier.frontier_id)}</Badge>
                      <Badge variant="outline">{formatBtstToken(frontier.status)}</Badge>
                    </div>
                    <p className="mt-2 text-xs leading-6 text-muted-foreground">{formatOptionalText(frontier.headline)}</p>
                    <p className="mt-2 text-xs leading-6 text-muted-foreground">影响样本：{formatStringList(frontier.best_variant_released_tickers)}</p>
                    <p className="mt-1 text-xs leading-6 text-muted-foreground">关注样本：{formatStringList(frontier.best_variant_focus_released_tickers)}</p>
                  </div>
                ))}
              </div>
            ) : null}
            <div className="rounded-md border border-border/60 bg-muted/20 p-3 space-y-2">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">执行车道</p>
                <p className="mt-1 text-xs leading-6 text-muted-foreground">直接查看 primary、shadow、recurring、structural 车道，并跳到对应回放上下文。</p>
              </div>
              {btstControlTowerOverview.rollout_lane_rows.length > 0 ? btstControlTowerOverview.rollout_lane_rows.map((lane) => {
                const laneContextParams = buildReplayContextParams(lane.context_reference, lane.ticker || 'all');
                return (
                  <div key={`${lane.lane_id || lane.ticker || 'lane'}-${lane.governance_tier || 'tier'}`} className="rounded-md border border-border/50 bg-background/60 px-3 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap gap-2">
                          <Badge variant="secondary">{formatOptionalText(lane.ticker)}</Badge>
                          <Badge variant="outline">{formatBtstToken(lane.governance_tier)}</Badge>
                        </div>
                        <p className="mt-2 text-xs leading-6 text-muted-foreground">车道状态：{formatBtstToken(lane.lane_status)}</p>
                        <p className="text-xs leading-6 text-muted-foreground">阻塞原因：{formatBtstToken(lane.blocker)}</p>
                        <p className="text-xs leading-6 text-muted-foreground">验证结论：{formatBtstToken(lane.validation_verdict)}{lane.missing_window_count !== null && lane.missing_window_count !== undefined ? ` | 缺失窗口 ${lane.missing_window_count}` : ''}</p>
                      </div>
                      {onOpenContext && laneContextParams ? (
                        <Button
                          type="button"
                          variant="secondary"
                          size="sm"
                          aria-label={`打开回放 ${lane.ticker || 'lane'}`}
                          onClick={() => onOpenContext(laneContextParams)}
                        >
                          打开回放
                        </Button>
                      ) : null}
                    </div>
                    <p className="mt-2 text-xs leading-6 text-muted-foreground">{formatBtstControlTowerLaneEvidence(lane)}</p>
                    <p className="mt-2 text-xs leading-6 text-muted-foreground">{formatOptionalText(lane.next_step)}</p>
                  </div>
                );
              }) : (
                <div className="rounded-md border border-border/50 bg-background/60 px-3 py-3 text-xs text-muted-foreground">
                  当前控制塔还没有可展示的执行车道。
                </div>
              )}
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 p-3 space-y-2">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">下一步动作</p>
                <p className="mt-1 text-xs leading-6 text-muted-foreground">控制塔给出的优先动作，可直接跳到对应回放。</p>
              </div>
              {btstControlTowerOverview.next_actions.length > 0 ? btstControlTowerOverview.next_actions.map((action) => (
                <div key={action.task_id || action.title || 'btst-control-action'} className="rounded-md border border-border/50 bg-background/60 px-3 py-3">
                  <p className="text-sm font-medium text-primary">{formatOptionalText(action.title)}</p>
                  <p className="mt-1 text-xs leading-6 text-muted-foreground">{formatOptionalText(action.why_now)}</p>
                  <p className="mt-2 text-xs leading-6 text-muted-foreground">{formatOptionalText(action.next_step)}</p>
                  {onOpenContext && buildReplayContextParams(action.context_reference || null) ? (
                    <div className="mt-3 flex justify-end">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        aria-label={`打开动作回放 ${action.task_id || action.title || 'task'}`}
                        onClick={() => {
                          const params = buildReplayContextParams(action.context_reference || null);
                          if (params) {
                            onOpenContext(params);
                          }
                        }}
                      >
                        打开回放
                      </Button>
                    </div>
                  ) : null}
                </div>
              )) : (
                <div className="rounded-md border border-border/50 bg-background/60 px-3 py-3 text-xs text-muted-foreground">
                  当前控制塔没有可展示的下一步动作。
                </div>
              )}
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 p-3 space-y-2">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">辅助资料</p>
              <p className="text-xs leading-6 text-muted-foreground">完整产物路径已收起到弹层，避免 inspector 被路径文本顶爆。</p>
              <div className="flex flex-wrap gap-2">
                <BtstArtifactSummaryPopover artifacts={btstControlTowerOverview.artifacts} />
              </div>
            </div>
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