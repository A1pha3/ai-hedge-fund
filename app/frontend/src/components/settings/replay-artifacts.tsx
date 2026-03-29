import { useEffect, useMemo, useState } from 'react';
import { BarChart3, Clock3, Database, RefreshCw, Wallet } from 'lucide-react';
import { toast } from 'sonner';
import { useAuth } from '@/contexts/auth-context';

import {
  replayArtifactApi,
  type ReplayArtifactDetail,
  type ReplayFeedbackActivity,
  type ReplayFeedbackRecord,
  type ReplayCacheBenchmarkOverview,
  type ReplayDualTargetRepresentativeCase,
  type ReplayLayerCAgentContribution,
  type ReplaySelectionArtifactDay,
  type ReplaySelectedCandidate,
  type ReplayArtifactSummary,
  type ReplayReasonCount,
  type ReplayRejectedCandidate,
  type ReplaySelectionArtifactDualTargetOverview,
  type ReplayTargetEvaluationResult,
  type ReplayWorkflowQueue,
  type ReplayWorkflowQueueItem,
} from '@/services/replay-artifact-api';
import { ReplayArtifactsInspector } from '@/components/replay-artifacts/replay-artifacts-inspector';
import { ReplayArtifactsReviewMarkdown } from '@/components/replay-artifacts/replay-artifacts-review-markdown';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';

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

function formatOptionalText(value: string | null | undefined): string {
  if (!value) {
    return '--';
  }
  return value;
}

function formatCompactDateToken(value: string): string {
  if (!/^\d{8}$/.test(value)) {
    return value;
  }
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
}

function formatCompactReportLabel(reportDir: string): string {
  const segments = reportDir
    .split('_')
    .filter(Boolean)
    .map((segment) => formatCompactDateToken(segment));

  if (segments.length <= 5) {
    return segments.join(' ');
  }

  return `${segments.slice(0, 5).join(' ')} ...`;
}

function formatPathLeaf(value: string | null | undefined): string {
  if (!value) {
    return '--';
  }
  const normalized = value.replace(/\\/g, '/');
  const segments = normalized.split('/').filter(Boolean);
  return segments.at(-1) || value;
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

function formatBooleanFlag(value: boolean | null | undefined): string {
  if (value === null || value === undefined) {
    return '--';
  }
  return value ? 'yes' : 'no';
}

function selectedCandidateBlocker(candidate: ReplaySelectedCandidate): string {
  return candidate.execution_bridge?.block_reason || '--';
}

function selectedCandidateTopFactors(candidate: ReplaySelectedCandidate): string {
  const topFactors = candidate.layer_b_summary?.top_factors || [];
  if (topFactors.length === 0) {
    return '--';
  }
  return topFactors
    .slice(0, 2)
    .map((factor) => {
      const numericValue = factor.value ?? factor.weight;
      if (typeof numericValue === 'number') {
        return `${factor.name}:${numericValue.toFixed(3)}`;
      }
      return factor.name;
    })
    .join(' | ');
}

function rejectedCandidateReasons(candidate: ReplayRejectedCandidate): string {
  if (candidate.rejection_reason_codes.length > 0) {
    return candidate.rejection_reason_codes.join(' | ');
  }
  return candidate.rejection_reason_text || '--';
}

function candidateConsensusSummary(candidate: ReplaySelectedCandidate): string {
  const summary = candidate.layer_c_summary;
  if (!summary) {
    return '--';
  }
  return [
    `A${summary.active_agent_count ?? 0}`,
    `+${summary.positive_agent_count ?? 0}`,
    `-${summary.negative_agent_count ?? 0}`,
    `0${summary.neutral_agent_count ?? 0}`,
  ].join(' | ');
}

function candidateCohortSummary(candidate: ReplaySelectedCandidate): string {
  const cohortContributions = candidate.layer_c_summary?.cohort_contributions;
  if (!cohortContributions) {
    return '--';
  }
  const entries = Object.entries(cohortContributions);
  if (entries.length === 0) {
    return '--';
  }
  return entries
    .map(([cohort, contribution]) => `${cohort}:${contribution.toFixed(3)}`)
    .join(' | ');
}

function formatAgentContribution(agent: ReplayLayerCAgentContribution): string {
  const contribution = typeof agent.contribution === 'number' ? agent.contribution.toFixed(4) : '--';
  const confidence = typeof agent.confidence === 'number' ? agent.confidence.toFixed(1) : '--';
  return `${agent.agent_id} (${agent.cohort || 'unknown'}, c=${contribution}, conf=${confidence})`;
}

function candidateAgentList(agents: ReplayLayerCAgentContribution[] | undefined): string {
  if (!agents || agents.length === 0) {
    return '--';
  }
  return agents
    .slice(0, 3)
    .map(formatAgentContribution)
    .join(' | ');
}

function formatStringList(items: string[] | undefined, emptyLabel = '--'): string {
  if (!items || items.length === 0) {
    return emptyLabel;
  }
  return items.join(' | ');
}

function formatCounterMap(values: Record<string, number> | undefined, emptyLabel = '--'): string {
  if (!values) {
    return emptyLabel;
  }
  const entries = Object.entries(values);
  if (entries.length === 0) {
    return emptyLabel;
  }
  return entries
    .map(([key, value]) => `${key}:${value}`)
    .join(' | ');
}

function formatDualTargetOverviewCounts(overview: ReplaySelectionArtifactDualTargetOverview | null | undefined): string {
  if (!overview) {
    return '--';
  }
  return `R ${overview.research_selected_count}/${overview.research_near_miss_count}/${overview.research_rejected_count} | S ${overview.short_trade_selected_count}/${overview.short_trade_near_miss_count}/${overview.short_trade_blocked_count}/${overview.short_trade_rejected_count}`;
}

function formatDualTargetOverviewModes(overview: ReplaySelectionArtifactDualTargetOverview | null | undefined): string {
  return formatCounterMap(overview?.target_mode_counts);
}

function formatShortTradeProfileOverview(
  overview: ReplayArtifactSummary['selection_artifact_overview']['short_trade_profile_overview'] | null | undefined,
): string {
  if (!overview) {
    return '--';
  }
  const counts = formatCounterMap(overview.profile_name_counts);
  const latestName = formatOptionalText(overview.latest_profile_name);
  return `${counts} | latest ${latestName}`;
}

function formatTargetDecision(decision: ReplayTargetEvaluationResult | null | undefined): string {
  if (!decision) {
    return '--';
  }
  const blockers = decision.blockers || [];
  const blockerText = blockers.length > 0 ? ` | blockers ${blockers.slice(0, 2).join(', ')}` : '';
  return `${decision.decision || 'unknown'} | score ${formatNumber(decision.score_target, 3)}${blockerText}`;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function formatMetricValue(value: unknown): string {
  if (typeof value === 'number') {
    return value.toFixed(3);
  }
  if (typeof value === 'string' && value.trim()) {
    return value;
  }
  if (typeof value === 'boolean') {
    return value ? 'yes' : 'no';
  }
  return '--';
}

function formatReasonList(decision: ReplayTargetEvaluationResult | null | undefined): string {
  if (!decision) {
    return '--';
  }
  const reasonGroups = [decision.top_reasons || [], decision.rejection_reasons || [], decision.blockers || []];
  const flattened = reasonGroups.flat().filter(Boolean);
  if (flattened.length === 0) {
    return '--';
  }
  return flattened.slice(0, 4).join(' | ');
}

function formatTargetMetricHighlights(decision: ReplayTargetEvaluationResult | null | undefined): string {
  if (!decision) {
    return '--';
  }
  const metrics = asRecord(decision.metrics_payload);
  if (!metrics) {
    return '--';
  }
  const keys = decision.target_type === 'short_trade'
    ? ['breakout_freshness', 'trend_acceleration', 'volume_expansion_quality', 'catalyst_freshness', 'layer_c_alignment', 'stale_trend_repair_penalty', 'overhead_supply_penalty']
    : ['score_b', 'score_c', 'score_final', 'quality_score'];
  const highlights = keys
    .filter((key) => metrics[key] !== undefined)
    .slice(0, 4)
    .map((key) => `${key}:${formatMetricValue(metrics[key])}`);
  return highlights.length > 0 ? highlights.join(' | ') : '--';
}

function formatTargetProfile(decision: ReplayTargetEvaluationResult | null | undefined): string {
  const explainability = asRecord(decision?.explainability_payload);
  const profile = explainability?.target_profile;
  return typeof profile === 'string' && profile.trim() ? profile : '--';
}

function formatTargetSource(decision: ReplayTargetEvaluationResult | null | undefined): string {
  const explainability = asRecord(decision?.explainability_payload);
  const source = explainability?.source;
  return typeof source === 'string' && source.trim() ? source : '--';
}

function normalizeExplainabilityValue(value: string): string {
  const normalized = value.trim();
  return normalized && normalized !== '--' ? normalized : '__missing__';
}

function describeExplainabilityValue(value: string): string {
  return value === '__missing__' ? 'missing' : value;
}

function candidateTargetDecisionList(candidate: ReplaySelectedCandidate | ReplayRejectedCandidate): ReplayTargetEvaluationResult[] {
  return Object.values(candidate.target_decisions || {}).filter((decision): decision is ReplayTargetEvaluationResult => Boolean(decision));
}

function candidateMatchesExplainabilityFilters(
  candidate: ReplaySelectedCandidate | ReplayRejectedCandidate,
  filters: ExplainabilityFilterState,
): boolean {
  const hasActiveFilter = filters.profile !== 'all' || filters.source !== 'all' || filters.decision !== 'all';
  const decisions = candidateTargetDecisionList(candidate);
  if (decisions.length === 0) {
    return !hasActiveFilter;
  }
  return decisions.some((decision) => {
    const profileMatched = filters.profile === 'all' || normalizeExplainabilityValue(formatTargetProfile(decision)) === filters.profile;
    const sourceMatched = filters.source === 'all' || normalizeExplainabilityValue(formatTargetSource(decision)) === filters.source;
    const decisionMatched = filters.decision === 'all' || normalizeExplainabilityValue(decision.decision || '--') === filters.decision;
    return profileMatched && sourceMatched && decisionMatched;
  });
}

function getPipelineProfileName(snapshot: ReplaySelectionArtifactDay['snapshot'] | undefined): string {
  const pipelineConfig = asRecord(snapshot?.pipeline_config_snapshot);
  const shortTradeProfile = asRecord(pipelineConfig?.short_trade_target_profile);
  const name = shortTradeProfile?.name;
  return typeof name === 'string' && name.trim() ? name : '--';
}

function getPipelineProfileSelectThreshold(snapshot: ReplaySelectionArtifactDay['snapshot'] | undefined): string {
  const pipelineConfig = asRecord(snapshot?.pipeline_config_snapshot);
  const shortTradeProfile = asRecord(pipelineConfig?.short_trade_target_profile);
  const config = asRecord(shortTradeProfile?.config);
  return formatMetricValue(config?.select_threshold);
}

function selectedCandidateTargetDecision(candidate: ReplaySelectedCandidate, targetName: 'research' | 'short_trade'): string {
  return formatTargetDecision(candidate.target_decisions?.[targetName]);
}

function rejectedCandidateTargetDecision(candidate: ReplayRejectedCandidate, targetName: 'research' | 'short_trade'): string {
  return formatTargetDecision(candidate.target_decisions?.[targetName]);
}

function formatRepresentativeCase(caseItem: ReplayDualTargetRepresentativeCase): string {
  const delta = caseItem.delta_classification || 'none';
  const researchDecision = caseItem.research_decision || 'none';
  const shortTradeDecision = caseItem.short_trade_decision || 'none';
  const summary = caseItem.delta_summary && caseItem.delta_summary.length > 0 ? ` | ${caseItem.delta_summary[0]}` : '';
  return `${caseItem.ticker} | ${delta} | research ${researchDecision} | short ${shortTradeDecision}${summary}`;
}

function countMapFromItems(items: string[]): Record<string, number> {
  return items.reduce<Record<string, number>>((counts, item) => {
    counts[item] = (counts[item] || 0) + 1;
    return counts;
  }, {});
}

type FeedbackFormState = {
  symbol: string;
  primaryTag: string;
  extraTags: string;
  reviewStatus: string;
  confidence: string;
  researchVerdict: string;
  notes: string;
};

type BatchFeedbackFormState = {
  selectedSymbols: string[];
  primaryTag: string;
  extraTags: string;
  reviewStatus: string;
  confidence: string;
  researchVerdict: string;
  notes: string;
};

type FeedbackFilterState = {
  symbol: string;
  reviewStatus: string;
};

type WorkflowQueueFilterState = {
  assignee: 'all' | 'me' | 'unassigned';
  workflowStatus: 'all' | 'unassigned' | 'assigned' | 'in_review' | 'ready_for_adjudication' | 'closed';
};

type ReportRailDualTargetFilterState = {
  targetMode: 'all' | 'dual_target' | 'research_only' | 'short_trade_only';
  deltaClass: string;
  shortTradeProfile: string;
};

type TradeDateDualTargetFilterState = {
  targetMode: 'all' | 'dual_target' | 'research_only' | 'short_trade_only';
  deltaClass: string;
  shortTradeProfile: string;
};

type ExplainabilityFilterState = {
  profile: string;
  source: string;
  decision: string;
};

type ReportRailSortMode = 'window_end_desc' | 'dual_target_days_desc' | 'delta_case_count_desc';

function promptList(items: string[] | undefined): string {
  if (!items || items.length === 0) {
    return '--';
  }
  return items.join(' | ');
}

function formatReasonCounts(reasonCounts: Record<string, unknown> | undefined): string {
  if (!reasonCounts) {
    return '--';
  }
  const entries = Object.entries(reasonCounts);
  if (entries.length === 0) {
    return '--';
  }
  return entries
    .slice(0, 3)
    .map(([reason, count]) => `${reason}:${count}`)
    .join(' | ');
}

function getFunnelFilter(snapshot: ReplaySelectionArtifactDay['snapshot'] | undefined, filterName: string): Record<string, unknown> {
  const filters = (snapshot?.funnel_diagnostics as { filters?: Record<string, Record<string, unknown>> } | undefined)?.filters;
  return filters?.[filterName] || {};
}

function getFilterTickers(filterPayload: Record<string, unknown>): Array<Record<string, unknown>> {
  const tickers = filterPayload.tickers;
  if (!Array.isArray(tickers)) {
    return [];
  }
  return tickers.filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null);
}

function formatFilterRow(row: Record<string, unknown>): string {
  const ticker = String(row.ticker || '--');
  const reason = String(row.reason || '--');
  const scoreFinal = typeof row.score_final === 'number' ? ` final=${row.score_final.toFixed(4)}` : '';
  const scoreB = typeof row.score_b === 'number' ? ` b=${row.score_b.toFixed(4)}` : '';
  const requiredScore = typeof row.required_score === 'number' ? ` req=${row.required_score.toFixed(4)}` : '';
  return `${ticker} | ${reason}${scoreFinal}${scoreB}${requiredScore}`;
}

function sortFeedbackRecords(records: ReplayFeedbackRecord[]): ReplayFeedbackRecord[] {
  return [...records].sort((left, right) => right.created_at.localeCompare(left.created_at));
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

interface ReplayArtifactsSettingsProps {
  mode?: 'settings' | 'workspace';
  className?: string;
}

export function ReplayArtifactsSettings({ mode = 'settings', className }: ReplayArtifactsSettingsProps) {
  const { user } = useAuth();
  const [reports, setReports] = useState<ReplayArtifactSummary[]>([]);
  const [selectedReport, setSelectedReport] = useState<string>('');
  const [detail, setDetail] = useState<ReplayArtifactDetail | null>(null);
  const [feedbackActivity, setFeedbackActivity] = useState<ReplayFeedbackActivity | null>(null);
  const [workflowQueue, setWorkflowQueue] = useState<ReplayWorkflowQueue | null>(null);
  const [selectedTradeDate, setSelectedTradeDate] = useState<string>('');
  const [selectionArtifactDetail, setSelectionArtifactDetail] = useState<ReplaySelectionArtifactDay | null>(null);
  const [isListLoading, setIsListLoading] = useState(true);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [isSelectionLoading, setIsSelectionLoading] = useState(false);
  const [isActivityLoading, setIsActivityLoading] = useState(false);
  const [isWorkflowQueueLoading, setIsWorkflowQueueLoading] = useState(false);
  const [isSubmittingFeedback, setIsSubmittingFeedback] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [workflowQueueError, setWorkflowQueueError] = useState<string | null>(null);
  const [feedbackForm, setFeedbackForm] = useState<FeedbackFormState>({
    symbol: '',
    primaryTag: '',
    extraTags: '',
    reviewStatus: 'draft',
    confidence: '0.50',
    researchVerdict: 'selected_for_good_reason',
    notes: '',
  });
  const [batchFeedbackForm, setBatchFeedbackForm] = useState<BatchFeedbackFormState>({
    selectedSymbols: [],
    primaryTag: '',
    extraTags: '',
    reviewStatus: 'draft',
    confidence: '0.50',
    researchVerdict: 'needs_weekly_review',
    notes: '',
  });
  const [feedbackFilter, setFeedbackFilter] = useState<FeedbackFilterState>({
    symbol: 'all',
    reviewStatus: 'all',
  });
  const [reportRailDualTargetFilter, setReportRailDualTargetFilter] = useState<ReportRailDualTargetFilterState>({
    targetMode: 'all',
    deltaClass: 'all',
    shortTradeProfile: 'all',
  });
  const [tradeDateDualTargetFilter, setTradeDateDualTargetFilter] = useState<TradeDateDualTargetFilterState>({
    targetMode: 'all',
    deltaClass: 'all',
    shortTradeProfile: 'all',
  });
  const [explainabilityFilter, setExplainabilityFilter] = useState<ExplainabilityFilterState>({
    profile: 'all',
    source: 'all',
    decision: 'all',
  });
  const [reportRailSortMode, setReportRailSortMode] = useState<ReportRailSortMode>('window_end_desc');
  const [focusedSymbol, setFocusedSymbol] = useState<string>('all');
  const [workflowQueueFilter, setWorkflowQueueFilter] = useState<WorkflowQueueFilterState>({
    assignee: 'me',
    workflowStatus: 'all',
  });
  const [queueCurrentReportOnly, setQueueCurrentReportOnly] = useState(false);
  const [queueFocusedSymbolOnly, setQueueFocusedSymbolOnly] = useState(false);

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
          const availableTradeDates = payload.selection_artifact_overview?.available_trade_dates || [];
          setSelectedTradeDate((current) => {
            if (current && availableTradeDates.includes(current)) {
              return current;
            }
            return availableTradeDates.at(-1) || '';
          });
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load replay detail');
          setDetail(null);
          setSelectionArtifactDetail(null);
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

  useEffect(() => {
    if (!selectedReport) {
      setFeedbackActivity(null);
      return;
    }

    let cancelled = false;

    async function loadFeedbackActivity() {
      setIsActivityLoading(true);
      setActivityError(null);
      try {
        const payload = await replayArtifactApi.getFeedbackActivity({
          reportName: selectedReport,
          limit: 8,
        });
        if (!cancelled) {
          setFeedbackActivity(payload);
        }
      } catch (loadError) {
        if (!cancelled) {
          setFeedbackActivity(null);
          setActivityError(loadError instanceof Error ? loadError.message : 'Failed to load replay feedback activity');
        }
      } finally {
        if (!cancelled) {
          setIsActivityLoading(false);
        }
      }
    }

    void loadFeedbackActivity();

    return () => {
      cancelled = true;
    };
  }, [selectedReport]);

  useEffect(() => {
    let cancelled = false;

    async function loadWorkflowQueue() {
      setIsWorkflowQueueLoading(true);
      setWorkflowQueueError(null);
      const assigneeFilter = workflowQueueFilter.assignee === 'all'
        ? undefined
        : workflowQueueFilter.assignee === 'me'
          ? user?.username
          : '__unassigned__';
      const workflowStatusFilter = workflowQueueFilter.workflowStatus === 'all' ? undefined : workflowQueueFilter.workflowStatus;
      try {
        const payload = await replayArtifactApi.getWorkflowQueue({
          assignee: assigneeFilter,
          workflowStatus: workflowStatusFilter,
          limit: 12,
        });
        if (!cancelled) {
          setWorkflowQueue(payload);
        }
      } catch (loadError) {
        if (!cancelled) {
          setWorkflowQueue(null);
          setWorkflowQueueError(loadError instanceof Error ? loadError.message : 'Failed to load replay workflow queue');
        }
      } finally {
        if (!cancelled) {
          setIsWorkflowQueueLoading(false);
        }
      }
    }

    void loadWorkflowQueue();

    return () => {
      cancelled = true;
    };
  }, [user?.username, workflowQueueFilter.assignee, workflowQueueFilter.workflowStatus]);

  useEffect(() => {
    if (!selectedReport || !selectedTradeDate) {
      setSelectionArtifactDetail(null);
      return;
    }

    let cancelled = false;

    async function loadSelectionArtifactDetail() {
      setIsSelectionLoading(true);
      setError(null);
      try {
        const payload = await replayArtifactApi.getSelectionArtifactDay(selectedReport, selectedTradeDate);
        if (!cancelled) {
          setSelectionArtifactDetail(payload);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load selection artifact detail');
          setSelectionArtifactDetail(null);
        }
      } finally {
        if (!cancelled) {
          setIsSelectionLoading(false);
        }
      }
    }

    void loadSelectionArtifactDetail();

    return () => {
      cancelled = true;
    };
  }, [selectedReport, selectedTradeDate]);

  const feedbackSummary = detail?.selection_artifact_overview?.feedback_summary as {
    overall?: { feedback_count?: number; final_feedback_count?: number };
    feedback_file_count?: number;
    trade_date_count?: number;
  } | null;
  const selectionSnapshot = selectionArtifactDetail?.snapshot;
  const selectedCandidates = useMemo(() => selectionSnapshot?.selected || [], [selectionSnapshot]);
  const rejectedCandidates = useMemo(() => selectionSnapshot?.rejected || [], [selectionSnapshot]);
  const universeSummary = selectionSnapshot?.universe_summary || {};
  const feedbackRecords = selectionArtifactDetail?.feedback_records || [];
  const sortedFeedbackRecords = sortFeedbackRecords(feedbackRecords);
  const feedbackOptions = selectionArtifactDetail?.feedback_options;
  const symbolOptions = useMemo(
    () => [
      ...selectedCandidates.map((candidate) => ({ symbol: candidate.symbol, scope: 'watchlist', label: `[watchlist] ${candidate.symbol}` })),
      ...rejectedCandidates.map((candidate) => ({ symbol: candidate.symbol, scope: 'near_miss', label: `[near_miss] ${candidate.symbol}` })),
    ],
    [rejectedCandidates, selectedCandidates],
  );
  const filteredFeedbackRecords = sortedFeedbackRecords.filter((record) => {
    const symbolMatched = feedbackFilter.symbol === 'all' || record.symbol === feedbackFilter.symbol;
    const statusMatched = feedbackFilter.reviewStatus === 'all' || record.review_status === feedbackFilter.reviewStatus;
    return symbolMatched && statusMatched;
  });
  const isWorkspace = mode === 'workspace';
  const layerBFilter = getFunnelFilter(selectionSnapshot, 'layer_b');
  const watchlistFilter = getFunnelFilter(selectionSnapshot, 'watchlist');
  const buyOrdersFilter = getFunnelFilter(selectionSnapshot, 'buy_orders');
  const targetSummary = selectionSnapshot?.target_summary;
  const researchTargetView = selectionSnapshot?.research_view;
  const shortTradeTargetView = selectionSnapshot?.short_trade_view;
  const dualTargetDelta = selectionSnapshot?.dual_target_delta;
  const reportDualTargetOverview = detail?.selection_artifact_overview?.dual_target_overview;
  const reportShortTradeProfileOverview = detail?.selection_artifact_overview?.short_trade_profile_overview;
  const btstFollowupOverview = detail?.selection_artifact_overview?.btst_followup_overview;
  const reportTargetModeOptions = useMemo(() => {
    const optionSet = new Set<string>();
    reports.forEach((report) => {
      Object.keys(report.selection_artifact_overview?.dual_target_overview?.target_mode_counts || {}).forEach((targetMode) => optionSet.add(targetMode));
    });
    return Array.from(optionSet).sort();
  }, [reports]);
  const reportDeltaClassOptions = useMemo(() => {
    const optionSet = new Set<string>();
    reports.forEach((report) => {
      Object.keys(report.selection_artifact_overview?.dual_target_overview?.delta_classification_counts || {}).forEach((deltaClass) => optionSet.add(deltaClass));
    });
    return Array.from(optionSet).sort();
  }, [reports]);
  const reportShortTradeProfileOptions = useMemo(() => {
    const optionSet = new Set<string>();
    reports.forEach((report) => {
      Object.keys(report.selection_artifact_overview?.short_trade_profile_overview?.profile_name_counts || {}).forEach((profileName) => optionSet.add(profileName));
    });
    return Array.from(optionSet).sort();
  }, [reports]);
  const filteredReports = useMemo(() => {
    const matchingReports = reports.filter((report) => {
      const dualTargetOverview = report.selection_artifact_overview?.dual_target_overview;
      const shortTradeProfileOverview = report.selection_artifact_overview?.short_trade_profile_overview;
      const targetModeMatched = reportRailDualTargetFilter.targetMode === 'all'
        || Boolean(dualTargetOverview?.target_mode_counts?.[reportRailDualTargetFilter.targetMode]);
      const deltaClassMatched = reportRailDualTargetFilter.deltaClass === 'all'
        || Boolean(dualTargetOverview?.delta_classification_counts?.[reportRailDualTargetFilter.deltaClass]);
      const shortTradeProfileMatched = reportRailDualTargetFilter.shortTradeProfile === 'all'
        || Boolean(shortTradeProfileOverview?.profile_name_counts?.[reportRailDualTargetFilter.shortTradeProfile]);
      return targetModeMatched && deltaClassMatched && shortTradeProfileMatched;
    });
    return [...matchingReports].sort((left, right) => {
      if (reportRailSortMode === 'dual_target_days_desc') {
        return (right.selection_artifact_overview.dual_target_overview?.dual_target_trade_date_count || 0)
          - (left.selection_artifact_overview.dual_target_overview?.dual_target_trade_date_count || 0);
      }
      if (reportRailSortMode === 'delta_case_count_desc') {
        const leftDeltaCount = Object.values(left.selection_artifact_overview.dual_target_overview?.delta_classification_counts || {}).reduce((sum, value) => sum + value, 0);
        const rightDeltaCount = Object.values(right.selection_artifact_overview.dual_target_overview?.delta_classification_counts || {}).reduce((sum, value) => sum + value, 0);
        return rightDeltaCount - leftDeltaCount;
      }
      return String(right.window.end_date || '').localeCompare(String(left.window.end_date || ''));
    });
  }, [reportRailDualTargetFilter.deltaClass, reportRailDualTargetFilter.shortTradeProfile, reportRailDualTargetFilter.targetMode, reportRailSortMode, reports]);
  const tradeDateTargetIndex = detail?.selection_artifact_overview?.trade_date_target_index || [];
  const tradeDateTargetModeOptions = useMemo(() => {
    const optionSet = new Set<string>();
    tradeDateTargetIndex.forEach((item) => {
      if (item.target_mode) {
        optionSet.add(item.target_mode);
      }
    });
    return Array.from(optionSet).sort();
  }, [tradeDateTargetIndex]);
  const tradeDateTargetModeCounts = useMemo(
    () => countMapFromItems(tradeDateTargetIndex.map((item) => item.target_mode).filter((item): item is string => Boolean(item))),
    [tradeDateTargetIndex],
  );
  const tradeDateDeltaClassOptions = useMemo(() => {
    const optionSet = new Set<string>();
    tradeDateTargetIndex.forEach((item) => {
      Object.keys(item.delta_classification_counts || {}).forEach((deltaClass) => optionSet.add(deltaClass));
    });
    return Array.from(optionSet).sort();
  }, [tradeDateTargetIndex]);
  const tradeDateDeltaClassCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    tradeDateTargetIndex.forEach((item) => {
      Object.keys(item.delta_classification_counts || {}).forEach((deltaClass) => {
        counts[deltaClass] = (counts[deltaClass] || 0) + 1;
      });
    });
    return counts;
  }, [tradeDateTargetIndex]);
  const tradeDateShortTradeProfileOptions = useMemo(() => {
    const optionSet = new Set<string>();
    tradeDateTargetIndex.forEach((item) => {
      if (item.short_trade_profile_name) {
        optionSet.add(item.short_trade_profile_name);
      }
    });
    return Array.from(optionSet).sort();
  }, [tradeDateTargetIndex]);
  const filteredTradeDateTargetIndex = useMemo(() => {
    return tradeDateTargetIndex.filter((item) => {
      const targetModeMatched = tradeDateDualTargetFilter.targetMode === 'all' || item.target_mode === tradeDateDualTargetFilter.targetMode;
      const deltaClassMatched = tradeDateDualTargetFilter.deltaClass === 'all' || Boolean(item.delta_classification_counts?.[tradeDateDualTargetFilter.deltaClass]);
      const shortTradeProfileMatched = tradeDateDualTargetFilter.shortTradeProfile === 'all' || item.short_trade_profile_name === tradeDateDualTargetFilter.shortTradeProfile;
      return targetModeMatched && deltaClassMatched && shortTradeProfileMatched;
    });
  }, [tradeDateDualTargetFilter.deltaClass, tradeDateDualTargetFilter.shortTradeProfile, tradeDateDualTargetFilter.targetMode, tradeDateTargetIndex]);
  const hasActiveTradeDateFilter = tradeDateDualTargetFilter.targetMode !== 'all' || tradeDateDualTargetFilter.deltaClass !== 'all' || tradeDateDualTargetFilter.shortTradeProfile !== 'all';
  const filteredAvailableTradeDates = useMemo(() => {
    if (hasActiveTradeDateFilter) {
      return filteredTradeDateTargetIndex.map((item) => item.trade_date);
    }
    if (filteredTradeDateTargetIndex.length > 0) {
      return filteredTradeDateTargetIndex.map((item) => item.trade_date);
    }
    return detail?.selection_artifact_overview?.available_trade_dates || [];
  }, [detail?.selection_artifact_overview?.available_trade_dates, filteredTradeDateTargetIndex, hasActiveTradeDateFilter]);
  const tradeDateFilterCoverageText = useMemo(() => {
    const total = detail?.selection_artifact_overview?.available_trade_dates?.length || 0;
    return `${filteredAvailableTradeDates.length} / ${total} trade dates`;
  }, [detail?.selection_artifact_overview?.available_trade_dates, filteredAvailableTradeDates.length]);
  const focusSymbolOptions = useMemo(
    () => [
      ...selectedCandidates.map((candidate) => candidate.symbol),
      ...rejectedCandidates.map((candidate) => candidate.symbol),
    ].filter((symbol, index, items) => items.indexOf(symbol) === index),
    [rejectedCandidates, selectedCandidates],
  );
  const explainabilityProfileOptions = useMemo(() => {
    const optionSet = new Set<string>();
    [...selectedCandidates, ...rejectedCandidates].forEach((candidate) => {
      candidateTargetDecisionList(candidate).forEach((decision) => {
        optionSet.add(normalizeExplainabilityValue(formatTargetProfile(decision)));
      });
    });
    return Array.from(optionSet).sort();
  }, [rejectedCandidates, selectedCandidates]);
  const explainabilitySourceOptions = useMemo(() => {
    const optionSet = new Set<string>();
    [...selectedCandidates, ...rejectedCandidates].forEach((candidate) => {
      candidateTargetDecisionList(candidate).forEach((decision) => {
        optionSet.add(normalizeExplainabilityValue(formatTargetSource(decision)));
      });
    });
    return Array.from(optionSet).sort();
  }, [rejectedCandidates, selectedCandidates]);
  const explainabilityDecisionOptions = useMemo(() => {
    const optionSet = new Set<string>();
    [...selectedCandidates, ...rejectedCandidates].forEach((candidate) => {
      candidateTargetDecisionList(candidate).forEach((decision) => {
        optionSet.add(normalizeExplainabilityValue(decision.decision || '--'));
      });
    });
    return Array.from(optionSet).sort();
  }, [rejectedCandidates, selectedCandidates]);
  const filteredSelectedCandidates = useMemo(
    () => selectedCandidates.filter((candidate) => (focusedSymbol === 'all' || candidate.symbol === focusedSymbol) && candidateMatchesExplainabilityFilters(candidate, explainabilityFilter)),
    [explainabilityFilter, focusedSymbol, selectedCandidates],
  );
  const filteredRejectedCandidates = useMemo(
    () => rejectedCandidates.filter((candidate) => (focusedSymbol === 'all' || candidate.symbol === focusedSymbol) && candidateMatchesExplainabilityFilters(candidate, explainabilityFilter)),
    [explainabilityFilter, focusedSymbol, rejectedCandidates],
  );
  const visibleFeedbackActivityRecords = useMemo(() => {
    const records = feedbackActivity?.recent_records || [];
    if (focusedSymbol === 'all') {
      return records;
    }
    return records.filter((record) => record.symbol === focusedSymbol);
  }, [feedbackActivity?.recent_records, focusedSymbol]);
  const visibleWorkflowQueueItems = useMemo(() => {
    const items = workflowQueue?.items || [];
    return items
      .filter((item) => {
        if (queueCurrentReportOnly && item.report_name !== selectedReport) {
          return false;
        }
        if (queueFocusedSymbolOnly && focusedSymbol !== 'all' && item.symbol !== focusedSymbol) {
          return false;
        }
        return true;
      })
      .sort((left, right) => {
      const leftScore = (left.report_name === selectedReport ? 2 : 0)
        + (left.trade_date === selectedTradeDate ? 2 : 0)
        + (focusedSymbol !== 'all' && left.symbol === focusedSymbol ? 4 : 0);
      const rightScore = (right.report_name === selectedReport ? 2 : 0)
        + (right.trade_date === selectedTradeDate ? 2 : 0)
        + (focusedSymbol !== 'all' && right.symbol === focusedSymbol ? 4 : 0);
      return rightScore - leftScore;
    });
  }, [focusedSymbol, queueCurrentReportOnly, queueFocusedSymbolOnly, selectedReport, selectedTradeDate, workflowQueue?.items]);
  const workflowFocusMatchCount = useMemo(() => {
    if (focusedSymbol === 'all') {
      return visibleWorkflowQueueItems.length;
    }
    return visibleWorkflowQueueItems.filter((item) => item.symbol === focusedSymbol).length;
  }, [focusedSymbol, visibleWorkflowQueueItems]);
  const tradeDateIndexRows = useMemo(() => {
    const rows = hasActiveTradeDateFilter ? filteredTradeDateTargetIndex : tradeDateTargetIndex;
    return [...rows].sort((left, right) => right.trade_date.localeCompare(left.trade_date));
  }, [filteredTradeDateTargetIndex, hasActiveTradeDateFilter, tradeDateTargetIndex]);

  useEffect(() => {
    if (!selectionArtifactDetail) {
      return;
    }
    setFeedbackForm((current) => {
      const nextSymbol = symbolOptions.some((item) => item.symbol === current.symbol)
        ? current.symbol
        : (symbolOptions[0]?.symbol || '');
      const allowedTags = feedbackOptions?.allowed_tags || [];
      const allowedStatuses = feedbackOptions?.allowed_review_statuses || [];
      return {
        ...current,
        symbol: nextSymbol,
        primaryTag: allowedTags.includes(current.primaryTag) ? current.primaryTag : (allowedTags[0] || ''),
        reviewStatus: allowedStatuses.includes(current.reviewStatus) ? current.reviewStatus : (allowedStatuses[0] || 'draft'),
      };
    });
    setBatchFeedbackForm((current) => {
      const allowedTags = feedbackOptions?.allowed_tags || [];
      const allowedStatuses = feedbackOptions?.allowed_review_statuses || [];
      return {
        ...current,
        selectedSymbols: current.selectedSymbols.filter((symbol) => symbolOptions.some((item) => item.symbol === symbol)),
        primaryTag: allowedTags.includes(current.primaryTag) ? current.primaryTag : (allowedTags[0] || ''),
        reviewStatus: allowedStatuses.includes(current.reviewStatus) ? current.reviewStatus : (allowedStatuses[0] || 'draft'),
      };
    });
  }, [selectionArtifactDetail, feedbackOptions, symbolOptions]);

  useEffect(() => {
    setReportRailDualTargetFilter((current) => {
      const nextShortTradeProfile = current.shortTradeProfile === 'all' || reportShortTradeProfileOptions.includes(current.shortTradeProfile)
        ? current.shortTradeProfile
        : 'all';
      if (nextShortTradeProfile === current.shortTradeProfile) {
        return current;
      }
      return {
        ...current,
        shortTradeProfile: nextShortTradeProfile,
      };
    });
  }, [reportShortTradeProfileOptions]);

  useEffect(() => {
    setTradeDateDualTargetFilter((current) => {
      const nextShortTradeProfile = current.shortTradeProfile === 'all' || tradeDateShortTradeProfileOptions.includes(current.shortTradeProfile)
        ? current.shortTradeProfile
        : 'all';
      if (nextShortTradeProfile === current.shortTradeProfile) {
        return current;
      }
      return {
        ...current,
        shortTradeProfile: nextShortTradeProfile,
      };
    });
  }, [tradeDateShortTradeProfileOptions]);

  useEffect(() => {
    if (focusedSymbol === 'all') {
      return;
    }
    if (!focusSymbolOptions.includes(focusedSymbol)) {
      setFocusedSymbol('all');
    }
  }, [focusSymbolOptions, focusedSymbol]);

  useEffect(() => {
    if (!selectionArtifactDetail) {
      return;
    }
    setExplainabilityFilter((current) => ({
      profile: current.profile === 'all' || explainabilityProfileOptions.includes(current.profile) ? current.profile : 'all',
      source: current.source === 'all' || explainabilitySourceOptions.includes(current.source) ? current.source : 'all',
      decision: current.decision === 'all' || explainabilityDecisionOptions.includes(current.decision) ? current.decision : 'all',
    }));
  }, [explainabilityDecisionOptions, explainabilityProfileOptions, explainabilitySourceOptions, selectionArtifactDetail]);

  useEffect(() => {
    if (filteredReports.length === 0) {
      return;
    }
    if (!filteredReports.some((report) => report.report_dir === selectedReport)) {
      setSelectedReport(filteredReports[0].report_dir);
    }
  }, [filteredReports, selectedReport]);

  useEffect(() => {
    if (filteredAvailableTradeDates.length === 0) {
      return;
    }
    if (!filteredAvailableTradeDates.includes(selectedTradeDate)) {
      setSelectedTradeDate(filteredAvailableTradeDates.at(-1) || '');
    }
  }, [filteredAvailableTradeDates, selectedTradeDate]);

  useEffect(() => {
    if (focusedSymbol === 'all') {
      setFeedbackFilter((current) => (current.symbol === 'all' ? current : { ...current, symbol: 'all' }));
      return;
    }

    setFeedbackFilter((current) => (current.symbol === focusedSymbol ? current : { ...current, symbol: focusedSymbol }));
    if (symbolOptions.some((item) => item.symbol === focusedSymbol)) {
      setFeedbackForm((current) => ({ ...current, symbol: focusedSymbol }));
      setBatchFeedbackForm((current) => ({
        ...current,
        selectedSymbols: current.selectedSymbols.includes(focusedSymbol) ? current.selectedSymbols : [focusedSymbol],
      }));
    }
  }, [focusedSymbol, symbolOptions]);

  function jumpToRepresentativeCase(caseItem: ReplayDualTargetRepresentativeCase) {
    if (caseItem.trade_date) {
      setSelectedTradeDate(caseItem.trade_date);
    }
    if (caseItem.ticker) {
      setFocusedSymbol(caseItem.ticker);
      setFeedbackFilter((current) => ({ ...current, symbol: caseItem.ticker }));
    }
  }

  async function refreshReplayArtifactContext(reportName: string, tradeDate: string) {
    let nextActivityError: string | null = null;
    let nextWorkflowQueueError: string | null = null;
    const assigneeFilter = workflowQueueFilter.assignee === 'all'
      ? undefined
      : workflowQueueFilter.assignee === 'me'
        ? user?.username
        : '__unassigned__';
    const workflowStatusFilter = workflowQueueFilter.workflowStatus === 'all' ? undefined : workflowQueueFilter.workflowStatus;
    const [nextDetail, nextSelectionArtifactDetail, nextFeedbackActivity, nextWorkflowQueue] = await Promise.all([
      replayArtifactApi.get(reportName),
      replayArtifactApi.getSelectionArtifactDay(reportName, tradeDate),
      replayArtifactApi.getFeedbackActivity({
        reportName,
        limit: 8,
      }).catch((activityLoadError) => {
        nextActivityError = activityLoadError instanceof Error ? activityLoadError.message : 'Failed to load replay feedback activity';
        return null;
      }),
      replayArtifactApi.getWorkflowQueue({
        assignee: assigneeFilter,
        workflowStatus: workflowStatusFilter,
        limit: 12,
      }).catch((workflowLoadError) => {
        nextWorkflowQueueError = workflowLoadError instanceof Error ? workflowLoadError.message : 'Failed to load replay workflow queue';
        return null;
      }),
    ]);
    setDetail(nextDetail);
    setSelectionArtifactDetail(nextSelectionArtifactDetail);
    setFeedbackActivity(nextFeedbackActivity);
    setActivityError(nextActivityError);
    setWorkflowQueue(nextWorkflowQueue);
    setWorkflowQueueError(nextWorkflowQueueError);
  }

  async function handleWorkflowQueueAssignment(item: ReplayWorkflowQueueItem) {
    if (!user?.username) {
      toast.error('当前用户不可用，无法更新 workflow queue');
      return;
    }
    const nextAssignee = item.assignee === user.username ? null : user.username;
    const nextWorkflowStatus = nextAssignee ? 'assigned' : 'unassigned';
    try {
      await replayArtifactApi.updateWorkflowQueueItem({
        report_name: item.report_name,
        trade_date: item.trade_date,
        symbol: item.symbol,
        review_scope: item.review_scope,
        assignee: nextAssignee,
        workflow_status: nextWorkflowStatus,
      });
      const assigneeFilter = workflowQueueFilter.assignee === 'all'
        ? undefined
        : workflowQueueFilter.assignee === 'me'
          ? user.username
          : '__unassigned__';
      const workflowStatusFilter = workflowQueueFilter.workflowStatus === 'all' ? undefined : workflowQueueFilter.workflowStatus;
      const nextQueue = await replayArtifactApi.getWorkflowQueue({
        assignee: assigneeFilter,
        workflowStatus: workflowStatusFilter,
        limit: 12,
      });
      setWorkflowQueue(nextQueue);
      setWorkflowQueueError(null);
      toast.success(nextAssignee ? 'workflow item 已归属到当前用户' : 'workflow item 已取消归属');
    } catch (updateError) {
      const message = updateError instanceof Error ? updateError.message : '更新 workflow queue 失败';
      setWorkflowQueueError(message);
      toast.error(message);
    }
  }

  function openWorkflowQueueItemContext(item: ReplayWorkflowQueueItem) {
    setSelectedReport(item.report_name);
    setSelectedTradeDate(item.trade_date);
    setFocusedSymbol(item.symbol);
    setFeedbackFilter((current) => ({ ...current, symbol: item.symbol }));
  }

  function openReplayContext(params: { reportName: string; tradeDate: string; symbol: string }) {
    setSelectedReport(params.reportName);
    setSelectedTradeDate(params.tradeDate);
    setFocusedSymbol(params.symbol);
    setFeedbackFilter((current) => ({ ...current, symbol: params.symbol }));
  }

  async function handleFeedbackSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedReport || !selectedTradeDate || !feedbackForm.symbol || !feedbackForm.primaryTag || !feedbackForm.researchVerdict) {
      toast.error('反馈表单缺少必填字段');
      return;
    }

    const symbolOption = symbolOptions.find((item) => item.symbol === feedbackForm.symbol);
    const tags = feedbackForm.extraTags
      .split(',')
      .map((item) => item.trim())
      .filter((item) => item.length > 0 && item !== feedbackForm.primaryTag);

    setIsSubmittingFeedback(true);
    setError(null);
    try {
      await replayArtifactApi.appendSelectionFeedback(selectedReport, selectedTradeDate, {
        symbol: feedbackForm.symbol,
        primary_tag: feedbackForm.primaryTag,
        research_verdict: feedbackForm.researchVerdict,
        tags,
        review_status: feedbackForm.reviewStatus,
        review_scope: symbolOption?.scope || 'watchlist',
        confidence: Number(feedbackForm.confidence),
        notes: feedbackForm.notes,
      });
      await refreshReplayArtifactContext(selectedReport, selectedTradeDate);
      setFeedbackForm((current) => ({
        ...current,
        extraTags: '',
        notes: '',
      }));
      toast.success('研究反馈已写入 selection artifact');
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : '提交 research feedback 失败';
      setError(message);
      toast.error(message);
    } finally {
      setIsSubmittingFeedback(false);
    }
  }

  function toggleBatchSymbol(symbol: string, checked: boolean) {
    setBatchFeedbackForm((current) => {
      if (checked) {
        if (current.selectedSymbols.includes(symbol)) {
          return current;
        }
        return { ...current, selectedSymbols: [...current.selectedSymbols, symbol] };
      }
      return { ...current, selectedSymbols: current.selectedSymbols.filter((item) => item !== symbol) };
    });
  }

  async function handleBatchFeedbackSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedReport || !selectedTradeDate || batchFeedbackForm.selectedSymbols.length === 0 || !batchFeedbackForm.primaryTag || !batchFeedbackForm.researchVerdict) {
      toast.error('批量标注缺少必填字段');
      return;
    }

    const tags = batchFeedbackForm.extraTags
      .split(',')
      .map((item) => item.trim())
      .filter((item) => item.length > 0 && item !== batchFeedbackForm.primaryTag);

    setIsSubmittingFeedback(true);
    setError(null);
    try {
      const result = await replayArtifactApi.appendSelectionFeedbackBatch(selectedReport, selectedTradeDate, {
        symbols: batchFeedbackForm.selectedSymbols,
        primary_tag: batchFeedbackForm.primaryTag,
        research_verdict: batchFeedbackForm.researchVerdict,
        tags,
        review_status: batchFeedbackForm.reviewStatus,
        confidence: Number(batchFeedbackForm.confidence),
        notes: batchFeedbackForm.notes,
      });
      await refreshReplayArtifactContext(selectedReport, selectedTradeDate);
      setBatchFeedbackForm((current) => ({
        ...current,
        selectedSymbols: [],
        extraTags: '',
        notes: '',
      }));
      toast.success(`已批量写入 ${result.appended_count} 条 research feedback`);
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : '提交批量 research feedback 失败';
      setError(message);
      toast.error(message);
    } finally {
      setIsSubmittingFeedback(false);
    }
  }

  return (
    <div className={cn('space-y-6', className)}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-primary">Replay Artifacts</h2>
          <p className={cn('mt-2 text-sm text-muted-foreground', isWorkspace ? 'max-w-4xl' : 'max-w-3xl')}>
            浏览 long-window replay 的基础绩效、关键 funnel 指标、按 ticker 执行摘要，以及按交易日的 selection review。一级工作台模式会把报告列表、主分析区和 inspector 拆开，避免继续挤在 settings 的单列内容区中。
          </p>
        </div>
        <Button variant="outline" onClick={() => window.location.reload()}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      {isWorkspace && !isDetailLoading && detail ? (
        <Card className="border-border/60 bg-muted/10">
          <CardContent className="grid gap-4 p-5 md:grid-cols-2 xl:grid-cols-4">
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-muted-foreground">Selected Window</p>
              <p className="mt-2 text-sm font-semibold text-primary">{detail.window.start_date} .. {detail.window.end_date}</p>
              <p className="mt-1 text-xs text-muted-foreground">{detail.run_header.plan_generation_mode || 'unknown mode'}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-muted-foreground">Model Route</p>
              <p className="mt-2 break-all text-sm font-semibold text-primary">{detail.run_header.model_provider || 'unknown provider'} / {detail.run_header.model_name || 'unknown model'}</p>
              <p className="mt-1 text-xs text-muted-foreground">report {detail.report_dir}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-muted-foreground">Selection Coverage</p>
              <p className="mt-2 text-sm font-semibold text-primary">{detail.selection_artifact_overview.trade_date_count} trade dates</p>
              <p className="mt-1 text-xs text-muted-foreground">feedback {feedbackSummary?.overall?.feedback_count || 0} / cache {formatCacheBenchmarkValue(detail.cache_benchmark_overview)}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-muted-foreground">Runtime Funnel</p>
              <p className="mt-2 text-sm font-semibold text-primary">L-B {formatNumber(detail.deployment_funnel_runtime.avg_layer_b_count, 2)} | WL {formatNumber(detail.deployment_funnel_runtime.avg_watchlist_count, 2)}</p>
              <p className="mt-1 text-xs text-muted-foreground">buy {formatNumber(detail.deployment_funnel_runtime.avg_buy_order_count, 2)} | day {formatNumber(detail.deployment_funnel_runtime.avg_total_day_seconds, 2)}s</p>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <div className={cn(isWorkspace ? 'grid gap-6 xl:grid-cols-[300px_minmax(0,1fr)_340px]' : 'space-y-6')}>
        <div className="space-y-4">
          {isWorkspace ? (
            <Card>
              <CardHeader>
                <CardTitle>Cross-Report Workflow Queue</CardTitle>
                <CardDescription>跨 report 的待复核队列，可查看我的待办或未归属样本，并直接 Assign to me / Unassign。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-1">
                  <label className="space-y-1 text-sm">
                    <span className="text-muted-foreground">Queue Scope</span>
                    <select
                      value={workflowQueueFilter.assignee}
                      onChange={(event) => setWorkflowQueueFilter((current) => ({ ...current, assignee: event.target.value as WorkflowQueueFilterState['assignee'] }))}
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                    >
                      <option value="me">my queue</option>
                      <option value="unassigned">unassigned</option>
                      <option value="all">all</option>
                    </select>
                  </label>
                  <label className="space-y-1 text-sm">
                    <span className="text-muted-foreground">Workflow Status</span>
                    <select
                      value={workflowQueueFilter.workflowStatus}
                      onChange={(event) => setWorkflowQueueFilter((current) => ({ ...current, workflowStatus: event.target.value as WorkflowQueueFilterState['workflowStatus'] }))}
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                    >
                      <option value="all">all</option>
                      <option value="unassigned">unassigned</option>
                      <option value="assigned">assigned</option>
                      <option value="in_review">in_review</option>
                      <option value="ready_for_adjudication">ready_for_adjudication</option>
                      <option value="closed">closed</option>
                    </select>
                  </label>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant={queueCurrentReportOnly ? 'default' : 'outline'} size="sm" onClick={() => setQueueCurrentReportOnly((current) => !current)}>
                    current report only
                  </Button>
                  <Button type="button" variant={queueFocusedSymbolOnly ? 'default' : 'outline'} size="sm" onClick={() => setQueueFocusedSymbolOnly((current) => !current)} disabled={focusedSymbol === 'all'}>
                    focus symbol only
                  </Button>
                </div>

                {isWorkflowQueueLoading ? (
                  <Skeleton className="h-32 w-full" />
                ) : workflowQueueError ? (
                  <p className="text-sm text-red-500">{workflowQueueError}</p>
                ) : workflowQueue ? (
                  <>
                    <div className="rounded-md border border-border/60 bg-muted/10 p-3">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Queue Summary</p>
                      <p className="mt-2 text-xs leading-6 text-muted-foreground">
                        {Object.entries(workflowQueue.workflow_status_counts || {}).map(([status, count]) => `${status}:${count}`).join(' | ') || '--'}
                      </p>
                      <p className="mt-1 text-xs leading-6 text-muted-foreground">visible {visibleWorkflowQueueItems.length} / {workflowQueue.items.length}</p>
                    </div>
                    <div className="space-y-3">
                      {visibleWorkflowQueueItems.length > 0 ? (
                        visibleWorkflowQueueItems.map((item) => (
                          <div key={`${item.report_name}-${item.trade_date}-${item.symbol}-${item.review_scope}`} className="rounded-md border border-border/60 bg-muted/10 p-3">
                            <div className="flex flex-wrap items-center gap-2">
                              <Badge variant="outline">{item.report_name}</Badge>
                              <Badge variant="secondary">{item.symbol}</Badge>
                              <Badge variant="outline">{item.workflow_status}</Badge>
                            </div>
                            <p className="mt-2 text-sm font-medium text-primary">{item.latest_primary_tag}</p>
                            <p className="mt-1 text-xs leading-6 text-muted-foreground">{item.trade_date} | {item.review_scope} | latest {item.latest_review_status}</p>
                            <p className="mt-1 text-xs leading-6 text-muted-foreground">assignee {item.assignee || '--'} | reviewer {item.latest_reviewer}</p>
                            <p className="mt-2 text-xs leading-6 text-muted-foreground">{item.latest_notes || '--'}</p>
                            <div className="mt-3 flex justify-end gap-2">
                              <Button type="button" variant="secondary" size="sm" onClick={() => openWorkflowQueueItemContext(item)}>
                                Open Context
                              </Button>
                              <Button type="button" variant="outline" size="sm" onClick={() => void handleWorkflowQueueAssignment(item)}>
                                {item.assignee === user?.username ? 'Unassign' : 'Assign to me'}
                              </Button>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-md border border-border/60 bg-muted/10 px-3 py-3 text-sm text-muted-foreground">
                          当前过滤条件下没有 workflow queue items。
                        </div>
                      )}
                    </div>
                  </>
                ) : null}
              </CardContent>
            </Card>
          ) : null}

          <Card className={cn(isWorkspace && 'xl:sticky xl:top-6')}>
            <CardHeader>
              <CardTitle>{isWorkspace ? 'Report Rail' : 'Report Selector'}</CardTitle>
              <CardDescription>
                当前接口直接扫描 data/reports 下可识别的 replay summary。{isWorkspace ? '左栏用于快速筛选和切换 replay 报告。' : ''}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {isListLoading ? (
                <Skeleton className="h-10 w-full" />
              ) : (
                <>
                  <select
                    value={selectedReport}
                    onChange={(event) => setSelectedReport(event.target.value)}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                  >
                    {filteredReports.map((report) => (
                      <option key={report.report_dir} value={report.report_dir}>
                        {formatCompactReportLabel(report.report_dir)}
                      </option>
                    ))}
                  </select>

                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-1">
                    <label className="space-y-1 text-sm">
                      <span className="text-muted-foreground">Report Target Mode Filter</span>
                      <select
                        value={reportRailDualTargetFilter.targetMode}
                        onChange={(event) => setReportRailDualTargetFilter((current) => ({ ...current, targetMode: event.target.value as ReportRailDualTargetFilterState['targetMode'] }))}
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                      >
                        <option value="all">all</option>
                        {reportTargetModeOptions.map((targetMode) => (
                          <option key={`target-mode-${targetMode}`} value={targetMode}>
                            {targetMode}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="text-muted-foreground">Report Delta Filter</span>
                      <select
                        value={reportRailDualTargetFilter.deltaClass}
                        onChange={(event) => setReportRailDualTargetFilter((current) => ({ ...current, deltaClass: event.target.value }))}
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                      >
                        <option value="all">all</option>
                        {reportDeltaClassOptions.map((deltaClass) => (
                          <option key={`delta-class-${deltaClass}`} value={deltaClass}>
                            {deltaClass}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="text-muted-foreground">Report Short Profile Filter</span>
                      <select
                        value={reportRailDualTargetFilter.shortTradeProfile}
                        onChange={(event) => setReportRailDualTargetFilter((current) => ({ ...current, shortTradeProfile: event.target.value }))}
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                      >
                        <option value="all">all</option>
                        {reportShortTradeProfileOptions.map((profileName) => (
                          <option key={`report-profile-${profileName}`} value={profileName}>
                            {profileName}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="text-muted-foreground">Report Sort</span>
                      <select
                        value={reportRailSortMode}
                        onChange={(event) => setReportRailSortMode(event.target.value as ReportRailSortMode)}
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                      >
                        <option value="window_end_desc">latest window end</option>
                        <option value="dual_target_days_desc">dual target days</option>
                        <option value="delta_case_count_desc">delta count</option>
                      </select>
                    </label>
                  </div>

                  <div className={cn('grid gap-3', isWorkspace ? 'grid-cols-1' : 'md:grid-cols-2 xl:grid-cols-3')}>
                    {filteredReports.map((report) => (
                      <button
                        key={report.report_dir}
                        type="button"
                        onClick={() => setSelectedReport(report.report_dir)}
                        className={`min-w-0 overflow-hidden rounded-md border px-3 py-3 text-left transition-colors ${selectedReport === report.report_dir ? 'border-primary bg-primary/5' : 'border-border/60 bg-muted/10 hover:bg-muted/20'}`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-semibold leading-5 text-primary">
                              {formatCompactReportLabel(report.report_dir)}
                            </p>
                            <p className="mt-1 break-all font-mono text-[11px] leading-5 text-muted-foreground" title={report.report_dir}>
                              {report.report_dir}
                            </p>
                          </div>
                          <Badge variant={selectedReport === report.report_dir ? 'secondary' : 'outline'} className="shrink-0 whitespace-nowrap">
                            {formatCacheBenchmarkValue(report.cache_benchmark_overview)}
                          </Badge>
                        </div>
                        <p className="mt-3 text-xs text-muted-foreground">
                          {formatOptionalText(report.window.start_date)} .. {formatOptionalText(report.window.end_date)}
                        </p>
                        <p className="mt-1 break-all text-xs leading-5 text-muted-foreground" title={`${formatOptionalText(report.run_header.model_provider)} / ${formatOptionalText(report.run_header.model_name)}`}>
                          {formatOptionalText(report.run_header.model_provider)} / {formatOptionalText(report.run_header.model_name)}
                        </p>
                        <p className="mt-2 break-all text-xs leading-5 text-muted-foreground">
                          {formatCacheBenchmarkDescription(report.cache_benchmark_overview)}
                        </p>
                        <p className="mt-2 text-xs leading-5 text-muted-foreground">
                          short profile {formatShortTradeProfileOverview(report.selection_artifact_overview.short_trade_profile_overview)}
                        </p>
                        <p className="mt-2 text-xs leading-5 text-muted-foreground">
                          target modes {formatDualTargetOverviewModes(report.selection_artifact_overview.dual_target_overview)}
                        </p>
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">
                          dual target {formatDualTargetOverviewCounts(report.selection_artifact_overview.dual_target_overview)}
                        </p>
                      </button>
                    ))}
                  </div>
                  {filteredReports.length === 0 ? (
                    <div className="rounded-md border border-border/60 bg-muted/10 px-3 py-3 text-sm text-muted-foreground">
                      当前筛选条件下没有匹配的 replay 报告。
                    </div>
                  ) : null}
                </>
              )}
              {error ? <p className="text-sm text-red-500">{error}</p> : null}
            </CardContent>
          </Card>

          {isWorkspace && !isDetailLoading && detail ? (
            <Card>
              <CardHeader>
                <CardTitle>Workspace Focus</CardTitle>
                <CardDescription>当前报告的快速上下文，方便在切换时做第一轮判断。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Return</span>
                  <span className="font-medium text-primary">{formatPercent(detail.headline_kpi.total_return_pct)}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Executed Days</span>
                  <span>{detail.headline_kpi.executed_trade_days ?? '--'}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Feedback Files</span>
                  <span>{feedbackSummary?.feedback_file_count || 0}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Selected Trade Date</span>
                  <span>{selectedTradeDate || '--'}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Focused Symbol</span>
                  <span>{focusedSymbol === 'all' ? '--' : focusedSymbol}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Dual Target Days</span>
                  <span>{reportDualTargetOverview?.dual_target_trade_date_count ?? '--'}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Short Profile</span>
                  <span>{reportShortTradeProfileOverview?.latest_profile_name || '--'}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Trade Date Filter</span>
                  <span>{tradeDateFilterCoverageText}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Focus Activity</span>
                  <span>{visibleFeedbackActivityRecords.length} / {feedbackActivity?.recent_records.length || 0}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Focus Queue</span>
                  <span>{workflowFocusMatchCount} / {workflowQueue?.items.length || 0}</span>
                </div>
                <div className="space-y-1 pt-1">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Modes</p>
                  <p className="text-xs leading-6 text-muted-foreground">{formatDualTargetOverviewModes(reportDualTargetOverview)}</p>
                </div>
                <div className="space-y-1 pt-1">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Short Trade Profiles</p>
                  <p className="text-xs leading-6 text-muted-foreground">{formatShortTradeProfileOverview(reportShortTradeProfileOverview)}</p>
                </div>
              </CardContent>
            </Card>
          ) : null}
        </div>

        <div className="space-y-6">
          {isDetailLoading || !detail ? (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <Skeleton className="h-36" />
              <Skeleton className="h-36" />
              <Skeleton className="h-36" />
              <Skeleton className="h-36" />
            </div>
          ) : (
            <>
              {!isWorkspace ? (
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">{detail.window.start_date} .. {detail.window.end_date}</Badge>
                  <Badge variant="secondary">{detail.run_header.plan_generation_mode || 'unknown mode'}</Badge>
                  <Badge variant="outline" className="max-w-full whitespace-normal break-all text-left leading-5">
                    {detail.run_header.model_provider || 'unknown provider'} / {detail.run_header.model_name || 'unknown model'}
                  </Badge>
                </div>
              ) : null}

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

              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-7">
                <KpiCard
                  title="Selection Days"
                  value={`${detail.selection_artifact_overview.trade_date_count}`}
                  description={detail.selection_artifact_overview.available ? 'Selection artifact 覆盖交易日数' : '当前 replay 未发现 selection artifacts'}
                  icon={Database}
                />
                <KpiCard
                  title="Write Status"
                  value={Object.entries(detail.selection_artifact_overview.write_status_counts || {})
                    .map(([status, count]) => `${status}:${count}`)
                    .join(' | ') || '--'}
                  description="来自 daily_events/current_plan.selection_artifacts.write_status"
                  icon={RefreshCw}
                />
                <KpiCard
                  title="Selection Blockers"
                  value={formatBlockers(detail.selection_artifact_overview.blocker_counts)}
                  description="按 selection snapshot 汇总的执行阻断原因"
                  icon={BarChart3}
                />
                <KpiCard
                  title="Dual Target"
                  value={reportDualTargetOverview ? `${reportDualTargetOverview.dual_target_trade_date_count} days` : '--'}
                  description={reportDualTargetOverview ? `modes ${formatDualTargetOverviewModes(reportDualTargetOverview)}` : '当前 report 还没有 report-level dual target 聚合'}
                  icon={BarChart3}
                />
                <KpiCard
                  title="Feedback Summary"
                  value={feedbackSummary?.overall?.feedback_count?.toString() || '0'}
                  description={`Final ${feedbackSummary?.overall?.final_feedback_count || 0} / Files ${feedbackSummary?.feedback_file_count || 0}`}
                  icon={Wallet}
                />
                <KpiCard
                  title="Cache Benchmark"
                  value={formatCacheBenchmarkValue(detail.cache_benchmark_overview)}
                  description={formatCacheBenchmarkDescription(detail.cache_benchmark_overview)}
                  icon={RefreshCw}
                />
                <KpiCard
                  title="BTST Follow-Up"
                  value={btstFollowupOverview?.primary_entry_ticker || '--'}
                  description={btstFollowupOverview ? `watch ${btstFollowupOverview.watchlist_count} / excluded ${btstFollowupOverview.excluded_research_count}` : '当前 report 还没有 BTST follow-up 产物'}
                  icon={BarChart3}
                />
              </div>

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

              <Card>
                <CardHeader>
                  <CardTitle>Selection Artifact Review</CardTitle>
                  <CardDescription>按交易日查看选股评审快照，直接暴露 watchlist 到 buy_order 的阻断原因。</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {reportDualTargetOverview ? (
                    <div className="rounded-md border border-border/60 bg-muted/10 p-4 space-y-2">
                      <div>
                        <p className="text-sm font-medium text-primary">Report-Level Dual Target Overview</p>
                        <p className="text-xs text-muted-foreground">先看整段 replay 的 target mode 分布和 delta 聚类，再决定要不要钻到某个 trade date。</p>
                      </div>
                      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                        <div className="rounded-md border border-border/50 bg-background/60 px-3 py-3">
                          <p className="text-xs uppercase tracking-wide text-muted-foreground">Target Modes</p>
                          <p className="mt-2 text-xs leading-6 text-muted-foreground">{formatDualTargetOverviewModes(reportDualTargetOverview)}</p>
                        </div>
                        <div className="rounded-md border border-border/50 bg-background/60 px-3 py-3">
                          <p className="text-xs uppercase tracking-wide text-muted-foreground">Aggregated Decisions</p>
                          <p className="mt-2 text-xs leading-6 text-muted-foreground">{formatDualTargetOverviewCounts(reportDualTargetOverview)}</p>
                        </div>
                        <div className="rounded-md border border-border/50 bg-background/60 px-3 py-3">
                          <p className="text-xs uppercase tracking-wide text-muted-foreground">Delta Counts</p>
                          <p className="mt-2 text-xs leading-6 text-muted-foreground">{formatCounterMap(reportDualTargetOverview.delta_classification_counts)}</p>
                        </div>
                        <div className="rounded-md border border-border/50 bg-background/60 px-3 py-3">
                          <p className="text-xs uppercase tracking-wide text-muted-foreground">Representative Cases</p>
                          <div className="mt-2 flex flex-wrap gap-2">
                            {reportDualTargetOverview.representative_cases.length > 0 ? (
                              reportDualTargetOverview.representative_cases.map((caseItem) => (
                                <Button
                                  key={`report-case-${caseItem.trade_date || 'none'}-${caseItem.ticker}-${caseItem.delta_classification || 'none'}`}
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  className="h-auto whitespace-normal px-3 py-2 text-left text-xs leading-5"
                                  onClick={() => jumpToRepresentativeCase(caseItem)}
                                >
                                  {caseItem.trade_date ? `${caseItem.trade_date} ` : ''}{formatRepresentativeCase(caseItem)}
                                </Button>
                              ))
                            ) : (
                              <p className="text-xs leading-6 text-muted-foreground">--</p>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : null}

                  {tradeDateIndexRows.length > 0 ? (
                    <div className="rounded-md border border-border/60 bg-muted/10 p-4 space-y-2">
                      <div>
                        <p className="text-sm font-medium text-primary">Trade Date Target Index</p>
                        <p className="text-xs text-muted-foreground">按 trade date 快速查看 target mode、delta 分布与主要计数，并可一键跳转。</p>
                      </div>
                      <div className="grid gap-2">
                        {tradeDateIndexRows.slice(0, 8).map((item) => (
                          <button
                            key={`trade-date-index-${item.trade_date}`}
                            type="button"
                            onClick={() => setSelectedTradeDate(item.trade_date)}
                            className={`rounded-md border px-3 py-3 text-left transition-colors ${selectedTradeDate === item.trade_date ? 'border-primary bg-primary/5' : 'border-border/60 bg-background/60 hover:bg-muted/20'}`}
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <span className="text-sm font-medium text-primary">{item.trade_date}</span>
                              <Badge variant="outline">{item.target_mode || 'unknown'}</Badge>
                            </div>
                            <p className="mt-1 text-xs leading-6 text-muted-foreground">profile {formatOptionalText(item.short_trade_profile_name)}</p>
                            <p className="mt-2 text-xs leading-6 text-muted-foreground">delta {formatCounterMap(item.delta_classification_counts)}</p>
                            <p className="mt-1 text-xs leading-6 text-muted-foreground">research {item.research_selected_count}/{item.research_near_miss_count} | short {item.short_trade_selected_count}/{item.short_trade_blocked_count}</p>
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5 md:items-end">
                    <label className="space-y-1 text-sm">
                      <span className="text-muted-foreground">Trade Date Target Mode Filter</span>
                      <select
                        value={tradeDateDualTargetFilter.targetMode}
                        onChange={(event) => setTradeDateDualTargetFilter((current) => ({ ...current, targetMode: event.target.value as TradeDateDualTargetFilterState['targetMode'] }))}
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                      >
                        <option value="all">all</option>
                        {tradeDateTargetModeOptions.map((targetMode) => (
                          <option key={`trade-date-target-mode-${targetMode}`} value={targetMode}>
                            {targetMode} ({tradeDateTargetModeCounts[targetMode] || 0})
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="text-muted-foreground">Trade Date Delta Filter</span>
                      <select
                        value={tradeDateDualTargetFilter.deltaClass}
                        onChange={(event) => setTradeDateDualTargetFilter((current) => ({ ...current, deltaClass: event.target.value }))}
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                      >
                        <option value="all">all</option>
                        {tradeDateDeltaClassOptions.map((deltaClass) => (
                          <option key={`trade-date-delta-class-${deltaClass}`} value={deltaClass}>
                            {deltaClass} ({tradeDateDeltaClassCounts[deltaClass] || 0})
                          </option>
                        ))}
                      </select>
                      <p className="text-xs text-muted-foreground">{tradeDateFilterCoverageText}</p>
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="text-muted-foreground">Trade Date Short Profile Filter</span>
                      <select
                        value={tradeDateDualTargetFilter.shortTradeProfile}
                        onChange={(event) => setTradeDateDualTargetFilter((current) => ({ ...current, shortTradeProfile: event.target.value }))}
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                      >
                        <option value="all">all</option>
                        {tradeDateShortTradeProfileOptions.map((profileName) => (
                          <option key={`trade-date-profile-${profileName}`} value={profileName}>
                            {profileName}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="text-muted-foreground">Trade Date</span>
                      {filteredAvailableTradeDates.length > 0 ? (
                        <select
                          value={selectedTradeDate}
                          onChange={(event) => setSelectedTradeDate(event.target.value)}
                          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                        >
                          {filteredAvailableTradeDates.map((tradeDate) => (
                            <option key={tradeDate} value={tradeDate}>
                              {tradeDate}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <p className="text-sm text-muted-foreground">当前 replay 没有可浏览的 selection artifact trade dates。</p>
                      )}
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="text-muted-foreground">Focus Symbol</span>
                      <select
                        value={focusedSymbol}
                        onChange={(event) => setFocusedSymbol(event.target.value)}
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                      >
                        <option value="all">all</option>
                        {focusSymbolOptions.map((symbol) => (
                          <option key={`focus-symbol-${symbol}`} value={symbol}>
                            {symbol}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="text-muted-foreground">Explainability Profile Filter</span>
                      <select
                        value={explainabilityFilter.profile}
                        onChange={(event) => setExplainabilityFilter((current) => ({ ...current, profile: event.target.value }))}
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                      >
                        <option value="all">all</option>
                        {explainabilityProfileOptions.map((profile) => (
                          <option key={`explainability-profile-${profile}`} value={profile}>
                            {describeExplainabilityValue(profile)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="text-muted-foreground">Explainability Source Filter</span>
                      <select
                        value={explainabilityFilter.source}
                        onChange={(event) => setExplainabilityFilter((current) => ({ ...current, source: event.target.value }))}
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                      >
                        <option value="all">all</option>
                        {explainabilitySourceOptions.map((source) => (
                          <option key={`explainability-source-${source}`} value={source}>
                            {describeExplainabilityValue(source)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="text-muted-foreground">Explainability Decision Filter</span>
                      <select
                        value={explainabilityFilter.decision}
                        onChange={(event) => setExplainabilityFilter((current) => ({ ...current, decision: event.target.value }))}
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                      >
                        <option value="all">all</option>
                        {explainabilityDecisionOptions.map((decision) => (
                          <option key={`explainability-decision-${decision}`} value={decision}>
                            {describeExplainabilityValue(decision)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <Button type="button" variant="outline" onClick={() => setFocusedSymbol('all')} disabled={focusedSymbol === 'all'}>
                      Clear Focus
                    </Button>
                  </div>
                  {filteredAvailableTradeDates.length === 0 ? (
                    <div className="rounded-md border border-border/60 bg-muted/10 px-3 py-3 text-sm text-muted-foreground">
                      当前 trade date 筛选条件下没有匹配的 selection artifact 日期。
                    </div>
                  ) : null}

                  {isSelectionLoading ? (
                    <Skeleton className="h-48 w-full" />
                  ) : selectionArtifactDetail ? (
                    <>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant="outline">{selectionArtifactDetail.trade_date}</Badge>
                        <Badge variant="secondary">feedback {selectionArtifactDetail.feedback_record_count}</Badge>
                        {focusedSymbol !== 'all' ? <Badge variant="secondary">focus {focusedSymbol}</Badge> : null}
                        {explainabilityFilter.profile !== 'all' ? <Badge variant="secondary">profile {describeExplainabilityValue(explainabilityFilter.profile)}</Badge> : null}
                        {explainabilityFilter.source !== 'all' ? <Badge variant="secondary">source {describeExplainabilityValue(explainabilityFilter.source)}</Badge> : null}
                        {explainabilityFilter.decision !== 'all' ? <Badge variant="secondary">decision {describeExplainabilityValue(explainabilityFilter.decision)}</Badge> : null}
                        {selectionArtifactDetail.blocker_counts.map((item) => (
                          <Badge key={`${item.reason}-${item.count}`} variant="outline">
                            {item.reason} x{item.count}
                          </Badge>
                        ))}
                      </div>
                      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                        <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-3">
                          <p className="text-xs uppercase tracking-wide text-muted-foreground">Watchlist</p>
                          <p className="mt-1 text-lg font-semibold">{String(universeSummary.watchlist_count ?? '--')}</p>
                        </div>
                        <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-3">
                          <p className="text-xs uppercase tracking-wide text-muted-foreground">Buy Orders</p>
                          <p className="mt-1 text-lg font-semibold">{String(universeSummary.buy_order_count ?? '--')}</p>
                        </div>
                        <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-3">
                          <p className="text-xs uppercase tracking-wide text-muted-foreground">High Pool</p>
                          <p className="mt-1 text-lg font-semibold">{String(universeSummary.high_pool_count ?? '--')}</p>
                        </div>
                        <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-3">
                          <p className="text-xs uppercase tracking-wide text-muted-foreground">Decision Time</p>
                          <p className="mt-1 break-all text-sm font-semibold leading-5">{formatOptionalText(selectionSnapshot?.decision_timestamp)}</p>
                        </div>
                      </div>

                      <div className="space-y-3">
                        <div>
                          <p className="text-sm font-medium text-primary">Dual Target Snapshot</p>
                          <p className="text-xs text-muted-foreground">直接消费 selection_snapshot 中的 target_summary、research_view、short_trade_view 与 dual_target_delta，不再依赖阅读 markdown 才知道双目标差异。</p>
                        </div>
                        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                          <div className="rounded-md border border-border/60 bg-muted/10 p-4">
                            <p className="text-xs uppercase tracking-wide text-muted-foreground">Target Mode</p>
                            <p className="mt-2 text-sm font-semibold text-primary">{formatOptionalText(selectionSnapshot?.target_mode)}</p>
                            <p className="mt-1 text-xs text-muted-foreground">selection targets {String(targetSummary?.selection_target_count ?? '--')}</p>
                          </div>
                          <div className="rounded-md border border-border/60 bg-muted/10 p-4">
                            <p className="text-xs uppercase tracking-wide text-muted-foreground">Short Trade Profile</p>
                            <p className="mt-2 text-sm font-semibold text-primary">{getPipelineProfileName(selectionSnapshot)}</p>
                            <p className="mt-1 text-xs text-muted-foreground">select {getPipelineProfileSelectThreshold(selectionSnapshot)}</p>
                          </div>
                          <div className="rounded-md border border-border/60 bg-muted/10 p-4">
                            <p className="text-xs uppercase tracking-wide text-muted-foreground">Research View</p>
                            <p className="mt-2 text-sm font-semibold text-primary">selected {String(targetSummary?.research_selected_count ?? 0)} | near {String(targetSummary?.research_near_miss_count ?? 0)}</p>
                            <p className="mt-1 text-xs text-muted-foreground">rejected {String(targetSummary?.research_rejected_count ?? 0)}</p>
                          </div>
                          <div className="rounded-md border border-border/60 bg-muted/10 p-4">
                            <p className="text-xs uppercase tracking-wide text-muted-foreground">Short Trade View</p>
                            <p className="mt-2 text-sm font-semibold text-primary">selected {String(targetSummary?.short_trade_selected_count ?? 0)} | near {String(targetSummary?.short_trade_near_miss_count ?? 0)}</p>
                            <p className="mt-1 text-xs text-muted-foreground">blocked {String(targetSummary?.short_trade_blocked_count ?? 0)} | rejected {String(targetSummary?.short_trade_rejected_count ?? 0)}</p>
                          </div>
                          <div className="rounded-md border border-border/60 bg-muted/10 p-4">
                            <p className="text-xs uppercase tracking-wide text-muted-foreground">Delta Counts</p>
                            <p className="mt-2 text-sm leading-6 text-primary">{formatCounterMap(targetSummary?.delta_classification_counts || dualTargetDelta?.delta_counts)}</p>
                            <p className="mt-1 text-xs text-muted-foreground">shell {String(targetSummary?.shell_target_count ?? 0)}</p>
                          </div>
                        </div>

                        <div className="grid gap-3 xl:grid-cols-3">
                          <div className="rounded-md border border-border/60 bg-muted/10 p-4 space-y-2">
                            <p className="text-xs uppercase tracking-wide text-muted-foreground">Research Target View</p>
                            <p className="text-sm">selected: {formatStringList(researchTargetView?.selected_symbols)}</p>
                            <p className="text-sm">near_miss: {formatStringList(researchTargetView?.near_miss_symbols)}</p>
                            <p className="text-sm">rejected: {formatStringList(researchTargetView?.rejected_symbols)}</p>
                            <p className="text-xs text-muted-foreground">blockers {formatCounterMap(researchTargetView?.blocker_counts)}</p>
                          </div>
                          <div className="rounded-md border border-border/60 bg-muted/10 p-4 space-y-2">
                            <p className="text-xs uppercase tracking-wide text-muted-foreground">Short Trade View</p>
                            <p className="text-sm">selected: {formatStringList(shortTradeTargetView?.selected_symbols)}</p>
                            <p className="text-sm">near_miss: {formatStringList(shortTradeTargetView?.near_miss_symbols)}</p>
                            <p className="text-sm">blocked: {formatStringList(shortTradeTargetView?.blocked_symbols)}</p>
                            <p className="text-sm">rejected: {formatStringList(shortTradeTargetView?.rejected_symbols)}</p>
                            <p className="text-xs text-muted-foreground">blockers {formatCounterMap(shortTradeTargetView?.blocker_counts)}</p>
                          </div>
                          <div className="rounded-md border border-border/60 bg-muted/10 p-4 space-y-2">
                            <p className="text-xs uppercase tracking-wide text-muted-foreground">Target Delta Highlights</p>
                            <p className="text-sm">dominant reasons: {formatStringList(dualTargetDelta?.dominant_delta_reasons)}</p>
                            <p className="text-xs text-muted-foreground">representative cases</p>
                            <div className="space-y-2">
                              {(dualTargetDelta?.representative_cases || []).length > 0 ? (
                                (dualTargetDelta?.representative_cases || []).slice(0, 5).map((caseItem) => (
                                  <Button
                                    key={`${caseItem.ticker}-${caseItem.delta_classification || 'none'}`}
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    className="h-auto w-full justify-start whitespace-normal px-3 py-2 text-left text-xs leading-6 text-muted-foreground"
                                    onClick={() => jumpToRepresentativeCase({ ...caseItem, trade_date: selectionArtifactDetail.trade_date })}
                                  >
                                    {formatRepresentativeCase(caseItem)}
                                  </Button>
                                ))
                              ) : (
                                <div className="rounded-md border border-border/50 bg-background/60 px-3 py-2 text-xs text-muted-foreground">No representative delta cases.</div>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="space-y-3">
                        <div>
                          <p className="text-sm font-medium text-primary">Selected Candidates</p>
                          <p className="text-xs text-muted-foreground">从 snapshot 直接读取 watchlist 级对象，方便并排对照 execution bridge 和 Layer B 因子。</p>
                        </div>
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Symbol</TableHead>
                              <TableHead>Final</TableHead>
                              <TableHead>Research Target</TableHead>
                              <TableHead>Short Trade Target</TableHead>
                              <TableHead>Layer C</TableHead>
                              <TableHead>Buy Order</TableHead>
                              <TableHead>Blocker</TableHead>
                              <TableHead>Top Factors</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {filteredSelectedCandidates.length > 0 ? (
                              filteredSelectedCandidates.map((candidate) => (
                                <TableRow key={`${candidate.symbol}-${candidate.rank_in_watchlist}`}>
                                  <TableCell className={cn('font-medium', focusedSymbol === candidate.symbol && 'text-primary')}>{candidate.symbol}</TableCell>
                                  <TableCell>{formatNumber(candidate.score_final, 4)}</TableCell>
                                  <TableCell>{selectedCandidateTargetDecision(candidate, 'research')}</TableCell>
                                  <TableCell>{selectedCandidateTargetDecision(candidate, 'short_trade')}</TableCell>
                                  <TableCell>{candidateConsensusSummary(candidate)}</TableCell>
                                  <TableCell>{formatBooleanFlag(candidate.execution_bridge?.included_in_buy_orders)}</TableCell>
                                  <TableCell>{selectedCandidateBlocker(candidate)}</TableCell>
                                  <TableCell>{selectedCandidateTopFactors(candidate)}</TableCell>
                                </TableRow>
                              ))
                            ) : (
                              <TableRow>
                                <TableCell colSpan={8} className="text-muted-foreground">No selected candidates match the current focus.</TableCell>
                              </TableRow>
                            )}
                          </TableBody>
                        </Table>
                      </div>

                      <div className="space-y-3">
                        <div>
                          <p className="text-sm font-medium text-primary">Layer C Analyst View</p>
                          <p className="text-xs text-muted-foreground">展示 selected candidates 的 analyst 共识、cohort 贡献，以及 top positive/negative agents。</p>
                        </div>
                        <div className="space-y-3">
                          {filteredSelectedCandidates.length > 0 ? (
                            filteredSelectedCandidates.map((candidate) => (
                              <div key={`layer-c-${candidate.symbol}-${candidate.rank_in_watchlist}`} className="rounded-md border border-border/60 bg-muted/10 p-4 space-y-3">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <div>
                                    <p className="text-sm font-medium text-primary">{candidate.symbol}</p>
                                    <p className="text-xs text-muted-foreground">adjusted_score_c {formatNumber(candidate.layer_c_summary?.adjusted_score_c, 4)} | raw_score_c {formatNumber(candidate.layer_c_summary?.raw_score_c, 4)}</p>
                                  </div>
                                  <Badge variant="outline">{candidateConsensusSummary(candidate)}</Badge>
                                </div>
                                <div className="grid gap-3 md:grid-cols-2">
                                  <div className="rounded-md border border-border/60 bg-background/60 px-3 py-3">
                                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Cohort Contributions</p>
                                    <p className="mt-2 text-sm">{candidateCohortSummary(candidate)}</p>
                                  </div>
                                  <div className="rounded-md border border-border/60 bg-background/60 px-3 py-3">
                                    <p className="text-xs uppercase tracking-wide text-muted-foreground">BC Conflict</p>
                                    <p className="mt-2 text-sm">{formatOptionalText(candidate.layer_c_summary?.bc_conflict || undefined)}</p>
                                  </div>
                                </div>
                                <div className="grid gap-3 md:grid-cols-2">
                                  <div className="rounded-md border border-emerald-200/60 bg-emerald-50/40 px-3 py-3 dark:border-emerald-900/40 dark:bg-emerald-950/10">
                                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Top Positive Agents</p>
                                    <p className="mt-2 text-sm leading-6">{candidateAgentList(candidate.layer_c_summary?.top_positive_agents)}</p>
                                  </div>
                                  <div className="rounded-md border border-rose-200/60 bg-rose-50/40 px-3 py-3 dark:border-rose-900/40 dark:bg-rose-950/10">
                                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Top Negative Agents</p>
                                    <p className="mt-2 text-sm leading-6">{candidateAgentList(candidate.layer_c_summary?.top_negative_agents)}</p>
                                  </div>
                                </div>
                              </div>
                            ))
                          ) : (
                            <div className="rounded-md border border-border/60 bg-muted/10 px-3 py-3 text-sm text-muted-foreground">
                              No Layer C candidate details match the current focus.
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="space-y-3">
                        <div>
                          <p className="text-sm font-medium text-primary">Research Prompts</p>
                          <p className="text-xs text-muted-foreground">直接展示 snapshot 中的 why_selected 和 what_to_check，方便研究员在填 feedback 时对照原始提示。</p>
                        </div>
                        <div className="space-y-3">
                          {filteredSelectedCandidates.length > 0 ? (
                            filteredSelectedCandidates.map((candidate) => (
                              <div key={`prompt-${candidate.symbol}-${candidate.rank_in_watchlist}`} className="rounded-md border border-border/60 bg-muted/10 p-4 space-y-3">
                                <div className="flex items-center justify-between gap-2">
                                  <p className="text-sm font-medium text-primary">{candidate.symbol}</p>
                                  <Badge variant="outline">{candidate.decision}</Badge>
                                </div>
                                <div className="grid gap-3 md:grid-cols-2">
                                  <div className="rounded-md border border-border/60 bg-background/60 px-3 py-3">
                                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Why Selected</p>
                                    <p className="mt-2 text-sm leading-6">{promptList(candidate.research_prompts?.why_selected)}</p>
                                  </div>
                                  <div className="rounded-md border border-border/60 bg-background/60 px-3 py-3">
                                    <p className="text-xs uppercase tracking-wide text-muted-foreground">What To Check</p>
                                    <p className="mt-2 text-sm leading-6">{promptList(candidate.research_prompts?.what_to_check)}</p>
                                  </div>
                                </div>
                              </div>
                            ))
                          ) : (
                            <div className="rounded-md border border-border/60 bg-muted/10 px-3 py-3 text-sm text-muted-foreground">
                              No research prompts match the current focus.
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="space-y-3">
                        <div>
                          <p className="text-sm font-medium text-primary">Target Explainability</p>
                          <p className="text-xs text-muted-foreground">把 target_decisions 里的 decision、reasons、profile、entry mode 和 metrics 摊平到 symbol 级工作台，减少在 snapshot JSON 和 markdown 之间来回跳转。</p>
                        </div>
                        <div className="space-y-3">
                          {[...filteredSelectedCandidates, ...filteredRejectedCandidates].length > 0 ? (
                            [...filteredSelectedCandidates, ...filteredRejectedCandidates].map((candidate) => {
                              const researchDecision = candidate.target_decisions?.research;
                              const shortTradeDecision = candidate.target_decisions?.short_trade;
                              return (
                                <div key={`target-explainability-${candidate.symbol}-${'rejection_stage' in candidate ? candidate.rejection_stage : candidate.rank_in_watchlist}`} className="rounded-md border border-border/60 bg-muted/10 p-4 space-y-3">
                                  <div className="flex flex-wrap items-center justify-between gap-2">
                                    <div>
                                      <p className="text-sm font-medium text-primary">{candidate.symbol}</p>
                                      <p className="text-xs text-muted-foreground">{'rejection_stage' in candidate ? `${candidate.rejection_stage} | final ${formatNumber(candidate.score_final, 4)}` : `watchlist rank ${candidate.rank_in_watchlist} | final ${formatNumber(candidate.score_final, 4)}`}</p>
                                    </div>
                                    <Badge variant="outline">{'rejection_stage' in candidate ? 'rejected/near-miss' : 'selected/watchlist'}</Badge>
                                  </div>
                                  <div className="grid gap-3 md:grid-cols-2">
                                    {[{ label: 'Research Target', decision: researchDecision }, { label: 'Short Trade Target', decision: shortTradeDecision }].map((item) => (
                                      <div key={`${candidate.symbol}-${item.label}`} className="rounded-md border border-border/60 bg-background/70 px-3 py-3 space-y-2">
                                        <div className="flex flex-wrap items-center justify-between gap-2">
                                          <p className="text-xs uppercase tracking-wide text-muted-foreground">{item.label}</p>
                                          <Badge variant="secondary">{item.decision?.decision || '--'}</Badge>
                                        </div>
                                        <p className="text-sm font-medium text-primary">score {item.decision ? formatNumber(item.decision.score_target, 3) : '--'} | confidence {item.decision ? formatNumber(item.decision.confidence, 3) : '--'}</p>
                                        <p className="text-xs leading-6 text-muted-foreground">profile {formatTargetProfile(item.decision)} | source {formatTargetSource(item.decision)}</p>
                                        <p className="text-xs leading-6 text-muted-foreground">holding {formatOptionalText(item.decision?.expected_holding_window)} | entry {formatOptionalText(item.decision?.preferred_entry_mode)}</p>
                                        <p className="text-xs leading-6 text-muted-foreground">reasons {formatReasonList(item.decision)}</p>
                                        <p className="text-xs leading-6 text-muted-foreground">metrics {formatTargetMetricHighlights(item.decision)}</p>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              );
                            })
                          ) : (
                            <div className="rounded-md border border-border/60 bg-muted/10 px-3 py-3 text-sm text-muted-foreground">
                              No target explainability records match the current focus.
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="space-y-3">
                        <div>
                          <p className="text-sm font-medium text-primary">Rejected Near Misses</p>
                          <p className="text-xs text-muted-foreground">如果有接近入选但落选的标的，这里直接展示 rejection stage 和 reason codes。</p>
                        </div>
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Symbol</TableHead>
                              <TableHead>Stage</TableHead>
                              <TableHead>Final</TableHead>
                              <TableHead>Research Target</TableHead>
                              <TableHead>Short Trade Target</TableHead>
                              <TableHead>Reasons</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {filteredRejectedCandidates.length > 0 ? (
                              filteredRejectedCandidates.map((candidate) => (
                                <TableRow key={`${candidate.symbol}-${candidate.rejection_stage}`}>
                                  <TableCell className={cn('font-medium', focusedSymbol === candidate.symbol && 'text-primary')}>{candidate.symbol}</TableCell>
                                  <TableCell>{candidate.rejection_stage}</TableCell>
                                  <TableCell>{formatNumber(candidate.score_final, 4)}</TableCell>
                                  <TableCell>{rejectedCandidateTargetDecision(candidate, 'research')}</TableCell>
                                  <TableCell>{rejectedCandidateTargetDecision(candidate, 'short_trade')}</TableCell>
                                  <TableCell>{rejectedCandidateReasons(candidate)}</TableCell>
                                </TableRow>
                              ))
                            ) : (
                              <TableRow>
                                <TableCell colSpan={6} className="text-muted-foreground">No near-miss rejected candidates match the current focus.</TableCell>
                              </TableRow>
                            )}
                          </TableBody>
                        </Table>
                      </div>

                      <div className="space-y-3">
                        <div>
                          <p className="text-sm font-medium text-primary">Funnel Drilldown</p>
                          <p className="text-xs text-muted-foreground">从 snapshot.funnel_diagnostics.filters 中直接展开 Layer B、watchlist、buy_orders 三层过滤结果，便于快速定位“卡在什么阶段、因为什么被过滤”。</p>
                        </div>
                        <div className="grid gap-3 md:grid-cols-3">
                          <div className="rounded-md border border-border/60 bg-muted/10 p-4 space-y-2">
                            <p className="text-xs uppercase tracking-wide text-muted-foreground">Layer B Filters</p>
                            <p className="text-sm">filtered_count: {String(layerBFilter.filtered_count ?? 0)}</p>
                            <p className="text-xs text-muted-foreground">{formatReasonCounts(layerBFilter.reason_counts as Record<string, unknown> | undefined)}</p>
                            <p className="text-xs leading-6 text-muted-foreground">{getFilterTickers(layerBFilter).slice(0, 3).map(formatFilterRow).join(' | ') || '--'}</p>
                          </div>
                          <div className="rounded-md border border-border/60 bg-muted/10 p-4 space-y-2">
                            <p className="text-xs uppercase tracking-wide text-muted-foreground">Watchlist Filters</p>
                            <p className="text-sm">filtered_count: {String(watchlistFilter.filtered_count ?? 0)}</p>
                            <p className="text-xs text-muted-foreground">{formatReasonCounts(watchlistFilter.reason_counts as Record<string, unknown> | undefined)}</p>
                            <p className="text-xs leading-6 text-muted-foreground">{getFilterTickers(watchlistFilter).slice(0, 3).map(formatFilterRow).join(' | ') || '--'}</p>
                          </div>
                          <div className="rounded-md border border-border/60 bg-muted/10 p-4 space-y-2">
                            <p className="text-xs uppercase tracking-wide text-muted-foreground">Buy Order Filters</p>
                            <p className="text-sm">filtered_count: {String(buyOrdersFilter.filtered_count ?? 0)}</p>
                            <p className="text-xs text-muted-foreground">{formatReasonCounts(buyOrdersFilter.reason_counts as Record<string, unknown> | undefined)}</p>
                            <p className="text-xs leading-6 text-muted-foreground">{getFilterTickers(buyOrdersFilter).slice(0, 3).map(formatFilterRow).join(' | ') || '--'}</p>
                          </div>
                        </div>
                      </div>

                      <div className="space-y-3 rounded-md border border-border/60 bg-muted/10 p-4">
                        <div>
                          <p className="text-sm font-medium text-primary">Batch Label Workspace</p>
                          <p className="text-xs text-muted-foreground">对当前 trade date 的多只 watchlist / near-miss 样本一次写入同一组标签，作为周度复盘和集中裁决的最小入口。</p>
                        </div>
                        <form className="space-y-4" onSubmit={handleBatchFeedbackSubmit}>
                          <div className="space-y-2">
                            <div className="flex items-center justify-between gap-3">
                              <span className="text-sm text-muted-foreground">Selected Symbols</span>
                              <Badge variant="secondary">{batchFeedbackForm.selectedSymbols.length} selected</Badge>
                            </div>
                            <div className="grid max-h-48 gap-2 overflow-y-auto rounded-md border border-border/60 bg-background/60 p-3 md:grid-cols-2">
                              {symbolOptions.length > 0 ? (
                                symbolOptions.map((item) => {
                                  const checked = batchFeedbackForm.selectedSymbols.includes(item.symbol);
                                  return (
                                    <label key={`batch-${item.scope}-${item.symbol}`} className="flex items-center gap-2 rounded-md border border-border/50 px-3 py-2 text-sm">
                                      <input
                                        type="checkbox"
                                        checked={checked}
                                        onChange={(event) => toggleBatchSymbol(item.symbol, event.target.checked)}
                                      />
                                      <span>{item.label}</span>
                                    </label>
                                  );
                                })
                              ) : (
                                <div className="text-sm text-muted-foreground">No batch label candidates available for this snapshot.</div>
                              )}
                            </div>
                          </div>

                          <div className="grid gap-3 md:grid-cols-2">
                            <label className="space-y-1 text-sm">
                              <span className="text-muted-foreground">Batch Primary Tag</span>
                              <select
                                value={batchFeedbackForm.primaryTag}
                                onChange={(event) => setBatchFeedbackForm((current) => ({ ...current, primaryTag: event.target.value }))}
                                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                              >
                                {(feedbackOptions?.allowed_tags || []).map((tag) => (
                                  <option key={`batch-tag-${tag}`} value={tag}>
                                    {tag}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <label className="space-y-1 text-sm">
                              <span className="text-muted-foreground">Batch Review Status</span>
                              <select
                                value={batchFeedbackForm.reviewStatus}
                                onChange={(event) => setBatchFeedbackForm((current) => ({ ...current, reviewStatus: event.target.value }))}
                                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                              >
                                {(feedbackOptions?.allowed_review_statuses || []).map((status) => (
                                  <option key={`batch-status-${status}`} value={status}>
                                    {status}
                                  </option>
                                ))}
                              </select>
                            </label>
                          </div>

                          <div className="grid gap-3 md:grid-cols-2">
                            <label className="space-y-1 text-sm">
                              <span className="text-muted-foreground">Batch Additional Tags</span>
                              <Input
                                value={batchFeedbackForm.extraTags}
                                onChange={(event) => setBatchFeedbackForm((current) => ({ ...current, extraTags: event.target.value }))}
                                placeholder="thesis_clear,crowded_trade_risk"
                              />
                            </label>
                            <label className="space-y-1 text-sm">
                              <span className="text-muted-foreground">Batch Confidence</span>
                              <Input
                                type="number"
                                min="0"
                                max="1"
                                step="0.01"
                                value={batchFeedbackForm.confidence}
                                onChange={(event) => setBatchFeedbackForm((current) => ({ ...current, confidence: event.target.value }))}
                              />
                            </label>
                          </div>

                          <label className="space-y-1 text-sm block">
                            <span className="text-muted-foreground">Batch Research Verdict</span>
                            <Input
                              value={batchFeedbackForm.researchVerdict}
                              onChange={(event) => setBatchFeedbackForm((current) => ({ ...current, researchVerdict: event.target.value }))}
                              placeholder="needs_weekly_review"
                            />
                          </label>

                          <label className="space-y-1 text-sm block">
                            <span className="text-muted-foreground">Batch Notes</span>
                            <textarea
                              value={batchFeedbackForm.notes}
                              onChange={(event) => setBatchFeedbackForm((current) => ({ ...current, notes: event.target.value }))}
                              rows={3}
                              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                              placeholder="记录这批样本为何需要统一推进到 final 或 weekly review。"
                            />
                          </label>

                          <div className="flex items-center justify-between gap-3">
                            <p className="text-xs text-muted-foreground">review_scope 会按 symbol 所属集合自动判定为 watchlist 或 near_miss。</p>
                            <Button type="submit" disabled={isSubmittingFeedback || batchFeedbackForm.selectedSymbols.length === 0}>
                              {isSubmittingFeedback ? 'Submitting...' : 'Append Batch Feedback'}
                            </Button>
                          </div>
                        </form>
                      </div>

                      <div className="space-y-3 rounded-md border border-border/60 bg-muted/10 p-4">
                        <div>
                          <p className="text-sm font-medium text-primary">Append Research Feedback</p>
                          <p className="text-xs text-muted-foreground">直接把结构化 research feedback 追加到当前 trade date 的 research_feedback.jsonl，并自动刷新 summary。</p>
                        </div>
                        <form className="space-y-3" onSubmit={handleFeedbackSubmit}>
                          <div className="grid gap-3 md:grid-cols-2">
                            <label className="space-y-1 text-sm">
                              <span className="text-muted-foreground">Symbol</span>
                              <select
                                value={feedbackForm.symbol}
                                onChange={(event) => setFeedbackForm((current) => ({ ...current, symbol: event.target.value }))}
                                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                              >
                                {symbolOptions.map((item) => (
                                  <option key={`${item.scope}-${item.symbol}`} value={item.symbol}>
                                    {item.label}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <label className="space-y-1 text-sm">
                              <span className="text-muted-foreground">Primary Tag</span>
                              <select
                                value={feedbackForm.primaryTag}
                                onChange={(event) => setFeedbackForm((current) => ({ ...current, primaryTag: event.target.value }))}
                                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                              >
                                {(feedbackOptions?.allowed_tags || []).map((tag) => (
                                  <option key={tag} value={tag}>
                                    {tag}
                                  </option>
                                ))}
                              </select>
                            </label>
                          </div>

                          <div className="grid gap-3 md:grid-cols-2">
                            <label className="space-y-1 text-sm">
                              <span className="text-muted-foreground">Additional Tags</span>
                              <Input
                                value={feedbackForm.extraTags}
                                onChange={(event) => setFeedbackForm((current) => ({ ...current, extraTags: event.target.value }))}
                                placeholder="thesis_clear,crowded_trade_risk"
                              />
                            </label>
                            <label className="space-y-1 text-sm">
                              <span className="text-muted-foreground">Review Status</span>
                              <select
                                value={feedbackForm.reviewStatus}
                                onChange={(event) => setFeedbackForm((current) => ({ ...current, reviewStatus: event.target.value }))}
                                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                              >
                                {(feedbackOptions?.allowed_review_statuses || []).map((status) => (
                                  <option key={status} value={status}>
                                    {status}
                                  </option>
                                ))}
                              </select>
                            </label>
                          </div>

                          <div className="grid gap-3 md:grid-cols-2">
                            <label className="space-y-1 text-sm">
                              <span className="text-muted-foreground">Research Verdict</span>
                              <Input
                                value={feedbackForm.researchVerdict}
                                onChange={(event) => setFeedbackForm((current) => ({ ...current, researchVerdict: event.target.value }))}
                                placeholder="selected_for_good_reason"
                              />
                            </label>
                            <label className="space-y-1 text-sm">
                              <span className="text-muted-foreground">Confidence</span>
                              <Input
                                type="number"
                                min="0"
                                max="1"
                                step="0.01"
                                value={feedbackForm.confidence}
                                onChange={(event) => setFeedbackForm((current) => ({ ...current, confidence: event.target.value }))}
                              />
                            </label>
                          </div>

                          <label className="space-y-1 text-sm block">
                            <span className="text-muted-foreground">Notes</span>
                            <textarea
                              value={feedbackForm.notes}
                              onChange={(event) => setFeedbackForm((current) => ({ ...current, notes: event.target.value }))}
                              rows={4}
                              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                              placeholder="记录为什么认为这次入选质量高或边际较弱。"
                            />
                          </label>

                          <div className="flex items-center justify-between gap-3">
                            <p className="text-xs text-muted-foreground">reviewer 会自动使用当前登录用户；summary 会在写入后自动重算。</p>
                            <Button type="submit" disabled={isSubmittingFeedback || symbolOptions.length === 0}>
                              {isSubmittingFeedback ? 'Submitting...' : 'Append Feedback'}
                            </Button>
                          </div>
                        </form>
                      </div>

                      <div className="space-y-3">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <p className="text-sm font-medium text-primary">Feedback Records</p>
                            <p className="text-xs text-muted-foreground">当前 trade date 已落盘的 research feedback 记录。</p>
                          </div>
                          <Badge variant="secondary">{selectionArtifactDetail.feedback_summary.feedback_count} records</Badge>
                        </div>
                        <div className="grid gap-3 md:grid-cols-2">
                          <label className="space-y-1 text-sm">
                            <span className="text-muted-foreground">Filter by Symbol</span>
                            <select
                              value={feedbackFilter.symbol}
                              onChange={(event) => setFeedbackFilter((current) => ({ ...current, symbol: event.target.value }))}
                              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                            >
                              <option value="all">all</option>
                              {Array.from(new Set(feedbackRecords.map((record) => record.symbol))).map((symbol) => (
                                <option key={symbol} value={symbol}>
                                  {symbol}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label className="space-y-1 text-sm">
                            <span className="text-muted-foreground">Filter by Status</span>
                            <select
                              value={feedbackFilter.reviewStatus}
                              onChange={(event) => setFeedbackFilter((current) => ({ ...current, reviewStatus: event.target.value }))}
                              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                            >
                              <option value="all">all</option>
                              {Array.from(new Set(feedbackRecords.map((record) => record.review_status))).map((status) => (
                                <option key={status} value={status}>
                                  {status}
                                </option>
                              ))}
                            </select>
                          </label>
                        </div>
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Symbol</TableHead>
                              <TableHead>Primary Tag</TableHead>
                              <TableHead>Status</TableHead>
                              <TableHead>Reviewer</TableHead>
                              <TableHead>Verdict</TableHead>
                              <TableHead>Created At</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {filteredFeedbackRecords.length > 0 ? (
                              filteredFeedbackRecords.map((record: ReplayFeedbackRecord) => (
                                <TableRow key={`${record.created_at}-${record.symbol}-${record.primary_tag}`}>
                                  <TableCell className="font-medium">{record.symbol}</TableCell>
                                  <TableCell>{record.primary_tag}</TableCell>
                                  <TableCell>{record.review_status}</TableCell>
                                  <TableCell>{record.reviewer}</TableCell>
                                  <TableCell>{record.research_verdict}</TableCell>
                                  <TableCell>{record.created_at}</TableCell>
                                </TableRow>
                              ))
                            ) : (
                              <TableRow>
                                <TableCell colSpan={6} className="text-muted-foreground">No feedback records match the current filters.</TableCell>
                              </TableRow>
                            )}
                          </TableBody>
                        </Table>
                      </div>

                      <ReplayArtifactsReviewMarkdown markdown={selectionArtifactDetail.review_markdown} />
                    </>
                  ) : (
                    <p className="text-sm text-muted-foreground">选择一个 trade date 以查看 selection review。</p>
                  )}
                </CardContent>
              </Card>

              {!isWorkspace ? (
                <>
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
                </>
              ) : null}
            </>
          )}
        </div>

        {isWorkspace ? (
          <ReplayArtifactsInspector
            detail={detail}
            selectionArtifactDetail={selectionArtifactDetail}
            feedbackActivity={feedbackActivity}
            focusedSymbol={focusedSymbol}
            selectedTradeDate={selectedTradeDate}
            tradeDateFilterCoverageText={tradeDateFilterCoverageText}
            visibleFeedbackActivityCount={visibleFeedbackActivityRecords.length}
            visibleWorkflowQueueCount={workflowFocusMatchCount}
            totalWorkflowQueueCount={workflowQueue?.items.length || 0}
            onOpenContext={openReplayContext}
            isDetailLoading={isDetailLoading}
            isActivityLoading={isActivityLoading}
            activityError={activityError}
          />
        ) : null}
      </div>
    </div>
  );
}