/**
 * P2-2: 回测参数对比 API 客户端。
 *
 * 对接后端 param_grid.py 的 ParamGridReport 数据结构:
 *   - 前端可直接展示 CLI --param-grid 输出的 JSON 结果
 *   - 或通过后端 API 端点获取已保存的对比报告
 *
 * 类型镜像后端 ParamGridTrial / ParamGridReport dataclass。
 */
import { authFetch } from '@/services/auth-api';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// ---------------------------------------------------------------------------
// Types (mirror backend param_grid.py)
// ---------------------------------------------------------------------------

/** 单次参数组合试验 (镜像 ParamGridTrial)。 */
export interface ParamTrial {
  trial_index: number;
  params: Record<string, unknown>;
  metrics: Record<string, number | string | null>;
  duration_seconds: number;
  error?: string | null;
}

/** 参数对比报告 (镜像 ParamGridReport)。 */
export interface ParamCompareReport {
  trials: ParamTrial[];
  total_combinations: number;
  max_workers: number;
}

/** 后端标准指标列 (COMPARISON_METRICS)。 */
export const COMPARISON_METRICS = [
  'sharpe_ratio',
  'sortino_ratio',
  'max_drawdown',
  'win_rate',
  'total_return',
  'window_count',
] as const;

export type ComparisonMetric = (typeof COMPARISON_METRICS)[number];

/** 指标显示名映射。 */
export const METRIC_LABELS: Record<string, string> = {
  sharpe_ratio: 'Sharpe',
  sortino_ratio: 'Sortino',
  max_drawdown: '最大回撤',
  win_rate: '胜率',
  total_return: '总收益',
  window_count: '交易窗口数',
};

/** 指标格式化规则 (百分比 / 小数)。 */
export function formatMetricValue(key: string, value: number | string | null): string {
  if (value == null) return '—';
  if (typeof value === 'string') return value;
  if (!Number.isFinite(value)) return '—';
  if (key === 'win_rate' || key === 'max_drawdown' || key === 'total_return') {
    return `${(value * 100).toFixed(1)}%`;
  }
  if (key === 'window_count') return String(Math.round(value));
  return value.toFixed(3);
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

async function _jsonOrThrow<T>(res: Response, label: string): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body && typeof body.detail === 'string') {
        detail = `${detail}: ${body.detail}`;
      }
    } catch {
      /* 非 JSON 响应 */
    }
    throw new Error(`${label} failed: ${detail}`);
  }
  return (await res.json()) as T;
}

export const paramCompareApi = {
  /**
   * 获取已保存的最近参数对比报告 (GET)。
   * 后端从 data/reports/ 读取最新 param_grid 结果。
   */
  async fetchLatest(): Promise<ParamCompareReport> {
    const res = await authFetch(`${API_BASE_URL}/api/backtest/param-compare`);
    return _jsonOrThrow<ParamCompareReport>(res, 'param-compare fetch');
  },

  /**
   * 提交对比结果 (POST) — 用于直接传入 CLI --param-grid JSON 输出。
   */
  async submit(report: ParamCompareReport): Promise<ParamCompareReport> {
    const res = await authFetch(`${API_BASE_URL}/api/backtest/param-compare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(report),
    });
    return _jsonOrThrow<ParamCompareReport>(res, 'param-compare submit');
  },
};
