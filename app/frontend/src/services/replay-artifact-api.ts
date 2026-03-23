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

export interface ReplayArtifactSummary {
  report_dir: string;
  window: ReplayWindow;
  run_header: ReplayRunHeader;
  headline_kpi: ReplayHeadlineKpi;
  deployment_funnel_runtime: ReplayDeploymentFunnelRuntime;
  artifacts: Record<string, string>;
}

export interface ReplaySelectionArtifactOverview {
  available: boolean;
  artifact_root?: string;
  trade_date_count: number;
  available_trade_dates: string[];
  write_status_counts: Record<string, number>;
  blocker_counts: ReplayReasonCount[];
  feedback_summary: Record<string, unknown> | null;
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
}

export interface ReplaySelectionSnapshot {
  artifact_version: string;
  run_id: string;
  experiment_id: string | null;
  trade_date: string;
  market: string;
  decision_timestamp: string;
  data_available_until: string;
  pipeline_config_snapshot: Record<string, unknown>;
  universe_summary: Record<string, number | string | boolean | null>;
  selected: ReplaySelectedCandidate[];
  rejected: ReplayRejectedCandidate[];
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
}

export const replayArtifactApi = new ReplayArtifactApiService();