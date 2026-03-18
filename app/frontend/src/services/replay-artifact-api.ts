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

export interface ReplayArtifactDetail extends ReplayArtifactSummary {
  ticker_execution_digest: ReplayTickerDigest[];
  final_portfolio_snapshot: Record<string, unknown>;
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
}

export const replayArtifactApi = new ReplayArtifactApiService();