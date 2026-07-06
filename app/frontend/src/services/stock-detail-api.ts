/**
 * P2-6: 标的深度分析 API 客户端。
 *
 * 对接后端 `app/backend/routes/screening.py`:
 *   GET /api/screening/stock-detail/{ticker}?trade_date=YYYYMMDD  → 单只标的深度分析
 *
 * 后端聚合 auto_screening 报告中单只标的的全部维度 (基本面 + 技术面 + 资金流 +
 * 系统历史: 推荐次数/连续推荐/信号衰减 + 同行业排名), 不调用外部 API。
 *
 * 类型严格镜像后端 Pydantic 模型 StockDetailResponse, 字段名一一对应。
 */
import { authFetch } from '@/services/auth-api';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/** 标的深度分析 (镜像后端 StockDetailResponse)。 */
export interface StockDetail {
  ticker: string;
  name: string;
  industry_sw: string;
  pe_ratio?: number | null;
  pb_ratio?: number | null;
  roe?: number | null;
  revenue_growth?: number | null;
  profit_growth?: number | null;
  dividend_yield?: number | null;
  price: number;
  change_pct: number;
  ma5?: number | null;
  ma20?: number | null;
  ma60?: number | null;
  rsi_14?: number | null;
  macd_signal: string;
  atr_pct?: number | null;
  money_flow_net?: number | null;
  north_money_net?: number | null;
  dragon_tiger: boolean;
  recommendation_count_30d: number;
  latest_score_b?: number | null;
  latest_decision?: string | null;
  latest_front_door_action?: string | null;
  consecutive_days: number;
  decay_level: string;
  industry_rank?: number | null;
  industry_total?: number | null;
}

async function _jsonOrThrow<T>(res: Response, label: string): Promise<T> {
  if (!res.ok) {
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

export const stockDetailApi = {
  /**
   * 拉取单只标的的深度分析 (GET)。trade_date 省略 = 最新报告。
   * 后端 404 表示无有效 auto_screening 报告 (需先运行 --auto)。
   */
  async fetch(ticker: string, tradeDate?: string): Promise<StockDetail> {
    const params = tradeDate ? `?trade_date=${encodeURIComponent(tradeDate)}` : '';
    const res = await authFetch(
      `${API_BASE_URL}/api/screening/stock-detail/${encodeURIComponent(ticker)}${params}`,
    );
    return _jsonOrThrow<StockDetail>(res, 'stock-detail fetch');
  },
};
