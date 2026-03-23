import { useEffect, useState } from 'react';
import { BarChart3, Clock3, Database, RefreshCw, Wallet } from 'lucide-react';
import { toast } from 'sonner';

import {
  replayArtifactApi,
  type ReplayArtifactDetail,
  type ReplayFeedbackRecord,
  type ReplayLayerCAgentContribution,
  type ReplaySelectionArtifactDay,
  type ReplaySelectedCandidate,
  type ReplayArtifactSummary,
  type ReplayReasonCount,
  type ReplayRejectedCandidate,
} from '@/services/replay-artifact-api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
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

function formatOptionalText(value: string | null | undefined): string {
  if (!value) {
    return '--';
  }
  return value;
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

type FeedbackFormState = {
  symbol: string;
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

export function ReplayArtifactsSettings() {
  const [reports, setReports] = useState<ReplayArtifactSummary[]>([]);
  const [selectedReport, setSelectedReport] = useState<string>('');
  const [detail, setDetail] = useState<ReplayArtifactDetail | null>(null);
  const [selectedTradeDate, setSelectedTradeDate] = useState<string>('');
  const [selectionArtifactDetail, setSelectionArtifactDetail] = useState<ReplaySelectionArtifactDay | null>(null);
  const [isListLoading, setIsListLoading] = useState(true);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [isSelectionLoading, setIsSelectionLoading] = useState(false);
  const [isSubmittingFeedback, setIsSubmittingFeedback] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedbackForm, setFeedbackForm] = useState<FeedbackFormState>({
    symbol: '',
    primaryTag: '',
    extraTags: '',
    reviewStatus: 'draft',
    confidence: '0.50',
    researchVerdict: 'selected_for_good_reason',
    notes: '',
  });
  const [feedbackFilter, setFeedbackFilter] = useState<FeedbackFilterState>({
    symbol: 'all',
    reviewStatus: 'all',
  });

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
  const selectedCandidates = selectionSnapshot?.selected || [];
  const rejectedCandidates = selectionSnapshot?.rejected || [];
  const universeSummary = selectionSnapshot?.universe_summary || {};
  const feedbackRecords = selectionArtifactDetail?.feedback_records || [];
  const sortedFeedbackRecords = sortFeedbackRecords(feedbackRecords);
  const feedbackOptions = selectionArtifactDetail?.feedback_options;
  const symbolOptions = [
    ...selectedCandidates.map((candidate) => ({ symbol: candidate.symbol, scope: 'watchlist', label: `[watchlist] ${candidate.symbol}` })),
    ...rejectedCandidates.map((candidate) => ({ symbol: candidate.symbol, scope: 'near_miss', label: `[near_miss] ${candidate.symbol}` })),
  ];
  const filteredFeedbackRecords = sortedFeedbackRecords.filter((record) => {
    const symbolMatched = feedbackFilter.symbol === 'all' || record.symbol === feedbackFilter.symbol;
    const statusMatched = feedbackFilter.reviewStatus === 'all' || record.review_status === feedbackFilter.reviewStatus;
    return symbolMatched && statusMatched;
  });
  const layerBFilter = getFunnelFilter(selectionSnapshot, 'layer_b');
  const watchlistFilter = getFunnelFilter(selectionSnapshot, 'watchlist');
  const buyOrdersFilter = getFunnelFilter(selectionSnapshot, 'buy_orders');

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
  }, [selectionArtifactDetail, feedbackOptions, symbolOptions]);

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
      const [nextDetail, nextSelectionArtifactDetail] = await Promise.all([
        replayArtifactApi.get(selectedReport),
        replayArtifactApi.getSelectionArtifactDay(selectedReport, selectedTradeDate),
      ]);
      setDetail(nextDetail);
      setSelectionArtifactDetail(nextSelectionArtifactDetail);
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

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-primary">Replay Artifacts</h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
            浏览 long-window replay 的基础绩效、关键 funnel 指标、按 ticker 执行摘要，以及按交易日的 selection review，避免直接翻原始 JSONL/Markdown。
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

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
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
              title="Feedback Summary"
              value={feedbackSummary?.overall?.feedback_count?.toString() || '0'}
              description={`Final ${feedbackSummary?.overall?.final_feedback_count || 0} / Files ${feedbackSummary?.feedback_file_count || 0}`}
              icon={Wallet}
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
                  <CardTitle>Selection Artifact Review</CardTitle>
                  <CardDescription>按交易日查看选股评审快照，直接暴露 watchlist 到 buy_order 的阻断原因。</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {detail.selection_artifact_overview.available_trade_dates.length > 0 ? (
                    <select
                      value={selectedTradeDate}
                      onChange={(event) => setSelectedTradeDate(event.target.value)}
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                    >
                      {detail.selection_artifact_overview.available_trade_dates.map((tradeDate) => (
                        <option key={tradeDate} value={tradeDate}>
                          {tradeDate}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <p className="text-sm text-muted-foreground">当前 replay 没有可浏览的 selection artifact trade dates。</p>
                  )}

                  {isSelectionLoading ? (
                    <Skeleton className="h-48 w-full" />
                  ) : selectionArtifactDetail ? (
                    <>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant="outline">{selectionArtifactDetail.trade_date}</Badge>
                        <Badge variant="secondary">feedback {selectionArtifactDetail.feedback_record_count}</Badge>
                        {selectionArtifactDetail.blocker_counts.map((item) => (
                          <Badge key={`${item.reason}-${item.count}`} variant="outline">
                            {item.reason} x{item.count}
                          </Badge>
                        ))}
                      </div>
                      <div className="space-y-2 text-xs text-muted-foreground">
                        <p className="break-all">snapshot: {selectionArtifactDetail.paths.snapshot_path}</p>
                        <p className="break-all">review: {selectionArtifactDetail.paths.review_path}</p>
                        <p className="break-all">feedback: {selectionArtifactDetail.paths.feedback_path}</p>
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
                          <p className="mt-1 text-sm font-semibold break-all">{formatOptionalText(selectionSnapshot?.decision_timestamp)}</p>
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
                              <TableHead>Layer C</TableHead>
                              <TableHead>Buy Order</TableHead>
                              <TableHead>Blocker</TableHead>
                              <TableHead>Top Factors</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {selectedCandidates.length > 0 ? (
                              selectedCandidates.map((candidate) => (
                                <TableRow key={`${candidate.symbol}-${candidate.rank_in_watchlist}`}>
                                  <TableCell className="font-medium">{candidate.symbol}</TableCell>
                                  <TableCell>{formatNumber(candidate.score_final, 4)}</TableCell>
                                  <TableCell>{candidateConsensusSummary(candidate)}</TableCell>
                                  <TableCell>{formatBooleanFlag(candidate.execution_bridge?.included_in_buy_orders)}</TableCell>
                                  <TableCell>{selectedCandidateBlocker(candidate)}</TableCell>
                                  <TableCell>{selectedCandidateTopFactors(candidate)}</TableCell>
                                </TableRow>
                              ))
                            ) : (
                              <TableRow>
                                <TableCell colSpan={6} className="text-muted-foreground">No selected candidates in this snapshot.</TableCell>
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
                          {selectedCandidates.length > 0 ? (
                            selectedCandidates.map((candidate) => (
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
                              No Layer C candidate details available for this snapshot.
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
                          {selectedCandidates.length > 0 ? (
                            selectedCandidates.map((candidate) => (
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
                              No research prompts available for this snapshot.
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
                              <TableHead>Reasons</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {rejectedCandidates.length > 0 ? (
                              rejectedCandidates.map((candidate) => (
                                <TableRow key={`${candidate.symbol}-${candidate.rejection_stage}`}>
                                  <TableCell className="font-medium">{candidate.symbol}</TableCell>
                                  <TableCell>{candidate.rejection_stage}</TableCell>
                                  <TableCell>{formatNumber(candidate.score_final, 4)}</TableCell>
                                  <TableCell>{rejectedCandidateReasons(candidate)}</TableCell>
                                </TableRow>
                              ))
                            ) : (
                              <TableRow>
                                <TableCell colSpan={4} className="text-muted-foreground">No near-miss rejected candidates recorded.</TableCell>
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

                      <pre className="max-h-[480px] overflow-auto rounded-md border border-border/60 bg-muted/20 p-3 text-xs leading-6 whitespace-pre-wrap">
                        {selectionArtifactDetail.review_markdown}
                      </pre>
                    </>
                  ) : (
                    <p className="text-sm text-muted-foreground">选择一个 trade date 以查看 selection review。</p>
                  )}
                </CardContent>
              </Card>

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
                <CardContent className="space-y-2 text-sm text-muted-foreground">
                  {Object.entries(detail.artifacts).map(([key, value]) => (
                    <div key={key} className="rounded-md border border-border/60 bg-muted/20 px-3 py-2">
                      <p className="font-medium text-primary">{key}</p>
                      <p className="break-all">{value}</p>
                    </div>
                  ))}
                  {detail.selection_artifact_overview.artifact_root ? (
                    <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2">
                      <p className="font-medium text-primary">selection_artifact_root</p>
                      <p className="break-all">{detail.selection_artifact_overview.artifact_root}</p>
                    </div>
                  ) : null}
                </CardContent>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}