/**
 * P1-6: 组合风险快照 API 客户端。
 *
 * 对接后端 `app/backend/routes/risk_metrics.py`:
 *   GET  /api/portfolio/risk-snapshot?lookback_days=N  → 空快照 (前端初始加载)
 *   POST /api/portfolio/risk-snapshot                   → 完整 payload 计算
 *   GET  /api/portfolio/risk-snapshot/thresholds        → 当前生效阈值 (诊断)
 *
 * 后端为纯计算服务 (无 I/O): 调用方 (前端 / paper_trading / 回测 / 审计) 注入
 * 持仓 + 回溯收益, 返回 RiskSnapshot (VaR / CVaR / 回撤 / 行业集中度)。
 *
 * 类型严格镜像后端 Pydantic 模型 (PositionInput / LookbackReturnInput /
 * RiskSnapshotRequest / RiskSnapshotResponse), 字段名一一对应。
 */
import { authFetch, authHeaders } from '@/services/auth-api';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/** 单只持仓输入 (镜像后端 PositionInput)。 */
export interface RiskSnapshotPosition {
  ticker: string;
  shares: number;
  current_price: number;
  market_value?: number | null;
  industry_sw?: string | null;
  beta?: number | null;
}

/** 单日单标的回溯收益 (镜像后端 LookbackReturnInput)。 */
export interface LookbackReturn {
  date: string;
  ticker: string;
  return_pct: number;
  portfolio_return?: number | null;
}

/** POST /api/portfolio/risk-snapshot 请求体 (镜像后端 RiskSnapshotRequest)。 */
export interface RiskSnapshotRequest {
  positions: RiskSnapshotPosition[];
  lookback_returns: LookbackReturn[];
  benchmark_returns?: number[] | null;
  initial_portfolio_value?: number | null;
  var_horizon_days?: number;
  confidence_levels?: number[];
  timestamp?: string;
}

/** 组合风险快照 (镜像后端 RiskSnapshotResponse)。
 *
 * 货币字段 (var_*, cvar_*) 单位与 portfolio_value 一致 (元);
 * max_drawdown / current_drawdown / industry_concentration 占比为小数 (0.12 = 12%)。
 */
export interface RiskSnapshot {
  timestamp: string;
  portfolio_value: number;
  var_95: number;
  var_99: number;
  cvar_95: number;
  cvar_99: number;
  max_drawdown: number;
  current_drawdown: number;
  drawdown_warning: boolean;
  industry_concentration: Record<string, number>;
  concentration_warning: boolean;
  single_position_max: number;
  position_count: number;
  beta_adjusted: number;
}

/** 诊断阈值 (镜像后端 _thresholds_dict)。 */
export interface RiskThresholds {
  industry_concentration: number;
  single_position: number;
  drawdown: number;
}

async function _jsonOrThrow<T>(res: Response, label: string): Promise<T> {
  if (!res.ok) {
    throw new Error(`${label} failed: HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export const riskSnapshotApi = {
  /**
   * 提交完整持仓 + 回溯收益, 计算实时风险快照 (POST)。
   * 适用于 paper_trading 运行时或前端「计算组合风险」按钮。
   */
  async compute(request: RiskSnapshotRequest): Promise<RiskSnapshot> {
    const res = await authFetch(`${API_BASE_URL}/api/portfolio/risk-snapshot`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(request),
    });
    return _jsonOrThrow<RiskSnapshot>(res, 'risk-snapshot compute');
  },

  /**
   * 获取空快照 (GET, 前端初始加载占位)。lookbackDays 仅用于缓存键, 不影响计算。
   */
  async fetchEmpty(lookbackDays = 60): Promise<RiskSnapshot> {
    const res = await authFetch(
      `${API_BASE_URL}/api/portfolio/risk-snapshot?lookback_days=${lookbackDays}`,
    );
    return _jsonOrThrow<RiskSnapshot>(res, 'risk-snapshot fetchEmpty');
  },

  /** 获取当前生效的预警阈值 (诊断端点)。 */
  async fetchThresholds(): Promise<RiskThresholds> {
    const res = await authFetch(
      `${API_BASE_URL}/api/portfolio/risk-snapshot/thresholds`,
    );
    return _jsonOrThrow<RiskThresholds>(res, 'risk-snapshot thresholds');
  },
};
