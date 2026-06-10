/**
 * P2-5: 自定义策略权重 API 客户端。
 *
 * 对接后端 `app/backend/routes/screening.py`:
 *   POST /api/screening/custom-weights  → 按用户自定义权重重算 score_b 并返回 Top N 推荐
 *
 * 后端用 4 个策略权重 (trend / mean_reversion / fundamental / event_sentiment)
 * 覆盖默认市场状态权重, 重新加权打分, 适合高级用户做敏感性分析 / 偏好测试。
 *
 * 类型严格镜像后端 Pydantic 模型 (CustomWeightsRequest / ScreeningResponse),
 * 字段名一一对应。权重和校验 (sum == 1.0) 在后端端点层执行 (422)。
 */
import { authFetch, authHeaders } from '@/services/auth-api';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/** 4 个策略权重 (每个 [0, 1], 之和必须为 1.0)。镜像后端 CustomWeightsRequest。 */
export interface CustomWeightsRequest {
  trend: number;
  mean_reversion: number;
  fundamental: number;
  event_sentiment: number;
  /** 返回的推荐数量, 默认 20, 范围 [1, 50]。 */
  top_n?: number;
  /** 指定交易日 (YYYYMMDD / YYYY-MM-DD); 省略 = 最新报告。 */
  trade_date?: string;
}

/** 单条推荐 (镜像后端 recommendations[].dict; 后端为 list[dict], 此处给出常用字段 + 索引签名)。 */
export interface ScreeningRecommendation {
  ticker: string;
  [key: string]: unknown;
}

/** 一键选股响应 (镜像后端 ScreeningResponse)。字段命名与 CLI --auto 报告 JSON 一致。 */
export interface ScreeningResponse {
  trade_date: string;
  recommendations: ScreeningRecommendation[];
  market_state?: Record<string, unknown> | null;
  tracking_summary?: Record<string, unknown> | null;
  consecutive_recommendation?: Record<string, unknown> | null;
  industry_rotation?: Record<string, unknown>[] | null;
  execution_time_seconds: number;
  batch_data_fetcher?: Record<string, unknown> | null;
  signal_decay_summary?: Record<string, unknown> | null;
  sector_concentration_warnings?: string[] | null;
  layer_a_count: number;
  total_scored: number;
  high_pool_count: number;
  top_n: number;
  meta: Record<string, unknown>;
}

/**
 * 4 个策略权重的和。供 UI 层在提交前做前置校验 (与后端 sum==1.0 ±1e-6 一致),
 * 避免无意义的 422 往返。
 */
export function sumWeights(weights: Pick<CustomWeightsRequest, 'trend' | 'mean_reversion' | 'fundamental' | 'event_sentiment'>): number {
  return weights.trend + weights.mean_reversion + weights.fundamental + weights.event_sentiment;
}

async function _jsonOrThrow<T>(res: Response, label: string): Promise<T> {
  if (!res.ok) {
    // 后端 422 (权重和 != 1.0) / 404 (无报告) 时, detail 在 JSON body 内 — 透传便于 UI 提示。
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body && typeof body.detail === 'string') {
        detail = `${detail}: ${body.detail}`;
      }
    } catch {
      /* 非 JSON 响应 — 仅保留状态码 */
    }
    throw new Error(`${label} failed: ${detail}`);
  }
  return (await res.json()) as T;
}

export const customWeightsApi = {
  /**
   * 应用自定义策略权重, 返回按新权重重排的 Top N 推荐 (POST)。
   *
   * 调用方应在提交前用 `sumWeights` 做前置校验 (sum ≈ 1.0), 后端仍会兜底校验。
   */
  async apply(request: CustomWeightsRequest): Promise<ScreeningResponse> {
    const res = await authFetch(`${API_BASE_URL}/api/screening/custom-weights`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(request),
    });
    return _jsonOrThrow<ScreeningResponse>(res, 'custom-weights apply');
  },
};
