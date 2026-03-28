import { authFetch } from './auth-api';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface ReplayWindow {
  start_date: string | null;
  end_date: string | null;
}

export interface ReplayRunHeader {
  mode: string | null;
  plan_generation_mode: string | null;
  model_provider: string | null;
  model_name: string | null;
}

export interface ReplayHeadlineKpi {
  initial_capital: number | null;
  final_value: number | null;
  total_return_pct: number | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  max_drawdown_pct: number | null;
  max_drawdown_date: string | null;
  executed_trade_days: number | null;
  total_executed_orders: number | null;
}

export interface ReplayReasonCount {
  reason: string;
  count: number;
}

export interface ReplayDeploymentFunnelRuntime {
  avg_invested_ratio: number | null;
  peak_invested_ratio: number | null;
  avg_layer_b_count: number | null;
  avg_watchlist_count: number | null;
  avg_buy_order_count: number | null;
  top_buy_blockers: ReplayReasonCount[];
  top_watchlist_blockers: ReplayReasonCount[];
  avg_total_day_seconds: number | null;
  avg_post_market_seconds: number | null;
}

export interface ReplayTickerDigest {
  ticker: string;
  buy_count: number;
  sell_count: number;
  final_long: number;
  realized_pnl: number;
  max_unrealized_pnl_pct: number;
  entry_score: number | null;
}

export interface ReplayCacheBenchmarkOverview {
  requested: boolean;
  executed: boolean;
  write_status: string | null;
  reason: string | null;
  ticker: string | null;
  trade_date: string | null;
  reuse_confirmed: boolean | null;
  disk_hit_gain: number | null;
  miss_reduction: number | null;
  set_reduction: number | null;
  first_hit_rate: number | null;
  second_hit_rate: number | null;
  artifacts: Record<string, string>;
}

export interface ReplayArtifactSummary {
  report_dir: string;
  window: ReplayWindow;
  run_header: ReplayRunHeader;
  headline_kpi: ReplayHeadlineKpi;
  deployment_funnel_runtime: ReplayDeploymentFunnelRuntime;
  artifacts: Record<string, string>;
  cache_benchmark_overview: ReplayCacheBenchmarkOverview;
  selection_artifact_overview: ReplaySelectionArtifactOverview;
}

export interface ReplaySelectionArtifactOverview {
  available: boolean;
  artifact_root?: string;
  trade_date_count: number;
  available_trade_dates: string[];
  trade_date_target_index?: ReplaySelectionArtifactTradeDateTargetSummary[];
  write_status_counts: Record<string, number>;
  blocker_counts: ReplayReasonCount[];
  dual_target_overview?: ReplaySelectionArtifactDualTargetOverview | null;
  feedback_summary: Record<string, unknown> | null;
}

export interface ReplaySelectionArtifactTradeDateTargetSummary {
  trade_date: string;
  target_mode?: string | null;
  delta_classification_counts: Record<string, number>;
  research_selected_count: number;
  research_near_miss_count: number;
  short_trade_selected_count: number;
  short_trade_blocked_count: number;
}

export interface ReplaySelectionArtifactDualTargetOverview {
  target_mode_counts: Record<string, number>;
  dual_target_trade_date_count: number;
  selection_target_count: number;
  research_target_count: number;
  short_trade_target_count: number;
  research_selected_count: number;
  research_near_miss_count: number;
  research_rejected_count: number;
  short_trade_selected_count: number;
  short_trade_near_miss_count: number;
  short_trade_blocked_count: number;
  short_trade_rejected_count: number;
  shell_target_count: number;
  delta_classification_counts: Record<string, number>;
  dominant_delta_reasons: string[];
  dominant_delta_reason_counts: Record<string, number>;
  representative_cases: ReplayDualTargetRepresentativeCase[];
}

export interface ReplaySelectionTopFactor {
  name: string;
  value?: number;
  weight?: number;
  source?: string;
}

export interface ReplaySelectionExecutionBridge {
  included_in_buy_orders?: boolean;
  planned_shares?: number;
  planned_amount?: number;
  target_weight?: number;
  block_reason?: string;
  blocked_until?: string;
  reentry_review_until?: string;
  exit_trade_date?: string;
  trigger_reason?: string;
}

export interface ReplayTargetEvaluationResult {
  target_type: 'research' | 'short_trade';
  decision: 'selected' | 'near_miss' | 'rejected' | 'blocked' | null;
  score_target: number;
  confidence: number;
  rank_hint?: number | null;
  positive_tags?: string[];
  negative_tags?: string[];
  blockers?: string[];
  top_reasons?: string[];
  rejection_reasons?: string[];
  gate_status?: Record<string, string>;
  expected_holding_window?: string | null;
  preferred_entry_mode?: string | null;
  metrics_payload?: Record<string, unknown>;
  explainability_payload?: Record<string, unknown>;
}

export interface ReplayDualTargetEvaluation {
  ticker: string;
  trade_date: string;
  research?: ReplayTargetEvaluationResult | null;
  short_trade?: ReplayTargetEvaluationResult | null;
  delta_classification?: string | null;
  delta_summary?: string[];
}

export interface ReplayDualTargetSummary {
  target_mode: 'research_only' | 'short_trade_only' | 'dual_target';
  selection_target_count: number;
  research_target_count: number;
  short_trade_target_count: number;
  research_selected_count: number;
  research_near_miss_count: number;
  research_rejected_count: number;
  short_trade_selected_count: number;
  short_trade_near_miss_count: number;
  short_trade_blocked_count?: number;
  short_trade_rejected_count: number;
  shell_target_count: number;
  delta_classification_counts?: Record<string, number>;
}

export interface ReplayResearchTargetView {
  selected_symbols: string[];
  near_miss_symbols: string[];
  rejected_symbols: string[];
  blocker_counts: Record<string, number>;
}

export interface ReplayShortTradeTargetView {
  selected_symbols: string[];
  near_miss_symbols: string[];
  rejected_symbols: string[];
  blocked_symbols: string[];
  blocker_counts: Record<string, number>;
}

export interface ReplayDualTargetRepresentativeCase {
  trade_date?: string;
  ticker: string;
  delta_classification?: string | null;
  research_decision?: string | null;
  short_trade_decision?: string | null;
  delta_summary?: string[];
}

export interface ReplayDualTargetDeltaView {
  delta_counts: Record<string, number>;
  representative_cases: ReplayDualTargetRepresentativeCase[];
  dominant_delta_reasons: string[];
}

export interface ReplayLayerCAgentContribution {
  agent_id: string;
  contribution: number;
  raw_contribution?: number;
  normalized_weight?: number;
  direction?: number;
  confidence?: number;
  completeness?: number;
  cohort?: string;
}

export interface ReplayLayerCSummary {
  active_agent_count?: number;
  positive_agent_count?: number;
  negative_agent_count?: number;
  neutral_agent_count?: number;
  raw_score_c?: number;
  adjusted_score_c?: number;
  cohort_contributions?: Record<string, number>;
  top_positive_agents?: ReplayLayerCAgentContribution[];
  top_negative_agents?: ReplayLayerCAgentContribution[];
  bc_conflict?: string | null;
}

export interface ReplaySelectedCandidate {
  symbol: string;
  name: string;
  decision: string;
  score_b: number;
  score_c: number;
  score_final: number;
  rank_in_watchlist: number;
  layer_b_summary?: {
    top_factors?: ReplaySelectionTopFactor[];
    explanation_source?: string;
    fallback_used?: boolean;
  };
  layer_c_summary?: ReplayLayerCSummary;
  execution_bridge?: ReplaySelectionExecutionBridge;
  research_prompts?: {
    why_selected?: string[];
    what_to_check?: string[];
  };
  target_context?: Record<string, unknown>;
  target_decisions?: Record<string, ReplayTargetEvaluationResult>;
}

export interface ReplayRejectedCandidate {
  symbol: string;
  name: string;
  rejection_stage: string;
  score_b: number;
  score_c: number;
  score_final: number;
  rejection_reason_codes: string[];
  rejection_reason_text: string;
  target_context?: Record<string, unknown>;
  target_decisions?: Record<string, ReplayTargetEvaluationResult>;
}

export interface ReplaySelectionSnapshot {
  artifact_version: string;
  run_id: string;
  experiment_id: string | null;
  trade_date: string;
  market: string;
  decision_timestamp: string;
  data_available_until: string;
  target_mode?: 'research_only' | 'short_trade_only' | 'dual_target';
  pipeline_config_snapshot: Record<string, unknown>;
  universe_summary: Record<string, number | string | boolean | null>;
  selected: ReplaySelectedCandidate[];
  rejected: ReplayRejectedCandidate[];
  selection_targets?: Record<string, ReplayDualTargetEvaluation>;
  target_summary?: ReplayDualTargetSummary;
  research_view?: ReplayResearchTargetView;
  short_trade_view?: ReplayShortTradeTargetView;
  dual_target_delta?: ReplayDualTargetDeltaView;
  buy_orders: Record<string, unknown>[];
  sell_orders: Record<string, unknown>[];
  funnel_diagnostics: Record<string, unknown>;
  artifact_status?: Record<string, unknown>;
}

export interface ReplayFeedbackRecord {
  feedback_version: string;
  artifact_version: string;
  label_version: string;
  run_id: string;
  trade_date: string;
  symbol: string;
  review_scope: string;
  reviewer: string;
  review_status: string;
  primary_tag: string;
  tags: string[];
  confidence: number;
  research_verdict: string;
  notes: string;
  created_at: string;
}

export interface ReplayFeedbackSummary {
  label_version: string;
  feedback_count: number;
  final_feedback_count: number;
  symbols: string[];
  reviewers: string[];
  primary_tag_counts: Record<string, number>;
  tag_counts: Record<string, number>;
  review_status_counts: Record<string, number>;
  verdict_counts: Record<string, number>;
  latest_created_at: string | null;
}

export interface ReplayFeedbackOptions {
  allowed_tags: string[];
  allowed_review_statuses: string[];
}

export interface ReplayArtifactDetail extends ReplayArtifactSummary {
  ticker_execution_digest: ReplayTickerDigest[];
  final_portfolio_snapshot: Record<string, unknown>;
  selection_artifact_overview: ReplaySelectionArtifactOverview;
}

export interface ReplaySelectionArtifactDay {
  report_dir: string;
  trade_date: string;
  paths: {
    snapshot_path: string;
    review_path: string;
    feedback_path: string;
  };
  snapshot: ReplaySelectionSnapshot;
  review_markdown: string;
  feedback_record_count: number;
  feedback_records: ReplayFeedbackRecord[];
  feedback_summary: ReplayFeedbackSummary;
  feedback_options: ReplayFeedbackOptions;
  blocker_counts: ReplayReasonCount[];
}

export interface ReplayFeedbackAppendRequest {
  symbol: string;
  primary_tag: string;
  research_verdict: string;
  tags?: string[];
  review_status?: string;
  review_scope?: string | null;
  confidence?: number;
  notes?: string;
  created_at?: string | null;
}

export interface ReplayFeedbackAppendResult {
  record: ReplayFeedbackRecord;
  feedback_record_count: number;
  feedback_summary: ReplayFeedbackSummary;
  directory_summary: Record<string, unknown>;
  feedback_path: string;
}

export interface ReplayFeedbackBatchAppendRequest {
  symbols: string[];
  primary_tag: string;
  research_verdict: string;
  tags?: string[];
  review_status?: string;
  confidence?: number;
  notes?: string;
  created_at?: string | null;
}

export interface ReplayFeedbackBatchAppendResult {
  records: ReplayFeedbackRecord[];
  appended_count: number;
  feedback_record_count: number;
  feedback_summary: ReplayFeedbackSummary;
  directory_summary: Record<string, unknown>;
  feedback_path: string;
}

export interface ReplayFeedbackActivityRecord {
  report_name: string;
  trade_date: string;
  symbol: string;
  review_scope: string;
  reviewer: string;
  review_status: string;
  primary_tag: string;
  tags: string[];
  confidence: number;
  research_verdict: string;
  notes: string;
  created_at: string;
  feedback_path: string;
}

export interface ReplayFeedbackActivity {
  report_name: string | null;
  reviewer: string | null;
  limit: number;
  record_count: number;
  recent_records: ReplayFeedbackActivityRecord[];
  review_status_counts: Record<string, number>;
  tag_counts: Record<string, number>;
  reviewer_counts: Record<string, number>;
  report_counts: Record<string, number>;
  workflow_status_counts?: Record<string, number>;
  workflow_queue?: Record<string, ReplayFeedbackActivityRecord[]>;
}

export interface ReplayWorkflowQueueItem {
  report_name: string;
  trade_date: string;
  symbol: string;
  review_scope: string;
  feedback_path: string;
  latest_feedback_created_at: string;
  latest_reviewer: string;
  latest_review_status: string;
  latest_primary_tag: string;
  latest_tags: string[];
  latest_research_verdict: string;
  latest_notes: string;
  assignee: string | null;
  workflow_status: string;
}

export interface ReplayWorkflowQueue {
  assignee: string | null;
  workflow_status: string | null;
  report_name: string | null;
  limit: number;
  item_count: number;
  items: ReplayWorkflowQueueItem[];
  workflow_status_counts: Record<string, number>;
  assignee_counts: Record<string, number>;
  report_counts: Record<string, number>;
}

export interface ReplayWorkflowQueueUpdateRequest {
  report_name: string;
  trade_date: string;
  symbol: string;
  review_scope: string;
  assignee?: string | null;
  workflow_status?: string | null;
}

class ReplayArtifactApiService {
  private readonly baseUrl = `${API_BASE_URL}/replay-artifacts`;

  async list(): Promise<ReplayArtifactSummary[]> {
    const response = await authFetch(this.baseUrl);
    if (!response.ok) {
      throw new Error('Failed to load replay artifacts');
    }
    const payload = await response.json();
    return payload.items as ReplayArtifactSummary[];
  }

  async get(reportName: string): Promise<ReplayArtifactDetail> {
    const response = await authFetch(`${this.baseUrl}/${encodeURIComponent(reportName)}`);
    if (!response.ok) {
      throw new Error('Failed to load replay artifact detail');
    }
    const payload = await response.json();
    return payload.report as ReplayArtifactDetail;
  }

  async getSelectionArtifactDay(reportName: string, tradeDate: string): Promise<ReplaySelectionArtifactDay> {
    const response = await authFetch(`${this.baseUrl}/${encodeURIComponent(reportName)}/selection-artifacts/${encodeURIComponent(tradeDate)}`);
    if (!response.ok) {
      throw new Error('Failed to load selection artifact detail');
    }
    const payload = await response.json();
    return payload.selection_artifact as ReplaySelectionArtifactDay;
  }

  async appendSelectionFeedback(reportName: string, tradeDate: string, request: ReplayFeedbackAppendRequest): Promise<ReplayFeedbackAppendResult> {
    const response = await authFetch(`${this.baseUrl}/${encodeURIComponent(reportName)}/selection-artifacts/${encodeURIComponent(tradeDate)}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Failed to append research feedback' }));
      throw new Error(error.detail || 'Failed to append research feedback');
    }
    const payload = await response.json();
    return payload.feedback as ReplayFeedbackAppendResult;
  }

  async appendSelectionFeedbackBatch(reportName: string, tradeDate: string, request: ReplayFeedbackBatchAppendRequest): Promise<ReplayFeedbackBatchAppendResult> {
    const response = await authFetch(`${this.baseUrl}/${encodeURIComponent(reportName)}/selection-artifacts/${encodeURIComponent(tradeDate)}/feedback/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Failed to append batch research feedback' }));
      throw new Error(error.detail || 'Failed to append batch research feedback');
    }
    const payload = await response.json();
    return payload.feedback as ReplayFeedbackBatchAppendResult;
  }

  async getFeedbackActivity(params: {
    reportName?: string;
    reviewer?: string;
    limit?: number;
  } = {}): Promise<ReplayFeedbackActivity> {
    const searchParams = new URLSearchParams();
    if (params.reportName) {
      searchParams.set('report_name', params.reportName);
    }
    if (params.reviewer) {
      searchParams.set('reviewer', params.reviewer);
    }
    if (typeof params.limit === 'number') {
      searchParams.set('limit', String(params.limit));
    }
    const query = searchParams.toString();
    const response = await authFetch(`${this.baseUrl}/feedback-activity${query ? `?${query}` : ''}`);
    if (!response.ok) {
      throw new Error('Failed to load replay feedback activity');
    }
    const payload = await response.json();
    return payload.activity as ReplayFeedbackActivity;
  }

  async getWorkflowQueue(params: {
    assignee?: string;
    workflowStatus?: string;
    reportName?: string;
    limit?: number;
  } = {}): Promise<ReplayWorkflowQueue> {
    const searchParams = new URLSearchParams();
    if (params.assignee) {
      searchParams.set('assignee', params.assignee);
    }
    if (params.workflowStatus) {
      searchParams.set('workflow_status', params.workflowStatus);
    }
    if (params.reportName) {
      searchParams.set('report_name', params.reportName);
    }
    if (typeof params.limit === 'number') {
      searchParams.set('limit', String(params.limit));
    }
    const query = searchParams.toString();
    const response = await authFetch(`${this.baseUrl}/workflow-queue${query ? `?${query}` : ''}`);
    if (!response.ok) {
      throw new Error('Failed to load replay workflow queue');
    }
    const payload = await response.json();
    return payload.queue as ReplayWorkflowQueue;
  }

  async updateWorkflowQueueItem(request: ReplayWorkflowQueueUpdateRequest): Promise<ReplayWorkflowQueueItem> {
    const response = await authFetch(`${this.baseUrl}/workflow-queue/item`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        report_name: request.report_name,
        trade_date: request.trade_date,
        symbol: request.symbol,
        review_scope: request.review_scope,
        assignee: request.assignee,
        workflow_status: request.workflow_status,
      }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Failed to update replay workflow item' }));
      throw new Error(error.detail || 'Failed to update replay workflow item');
    }
    const payload = await response.json();
    return payload.item as ReplayWorkflowQueueItem;
  }
}

export const replayArtifactApi = new ReplayArtifactApiService();