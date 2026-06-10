/**
 * P2-9: 宏观经济数据 API 客户端。
 *
 * 对接后端 src/data/macro_data.py:
 *   MacroSnapshot — CPI / PPI / PMI / M2 / 社融 / LPR + 派生标签
 *
 * 后端无独立 /api/macro 端点, 数据通过 market_state 聚合获取。
 * 此 service 层可直接用 MacroSnapshot JSON 渲染宏观仪表盘。
 */
import { authFetch } from '@/services/auth-api';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// ---------------------------------------------------------------------------
// Types (mirror backend MacroSnapshot)
// ---------------------------------------------------------------------------

/** 宏观快照 (镜像 MacroSnapshot dataclass)。 */
export interface MacroSnapshot {
  date: string;
  cpi_yoy: number | null;
  ppi_yoy: number | null;
  pmi_manufacturing: number | null;
  pmi_non_manufacturing: number | null;
  m2_yoy: number | null;
  social_financing: number | null;
  interest_rate_lpr_1y: number | null;
  inflation_pressure: string;
  monetary_stance: string;
  economic_momentum: string;
}

/** 指标显示名映射。 */
export const MACRO_LABELS: Record<string, string> = {
  cpi_yoy: 'CPI 同比',
  ppi_yoy: 'PPI 同比',
  pmi_manufacturing: '制造业 PMI',
  pmi_non_manufacturing: '非制造业 PMI',
  m2_yoy: 'M2 同比',
  social_financing: '社融规模',
  interest_rate_lpr_1y: '1年期 LPR',
};

/** 指标单位。 */
export const MACRO_UNITS: Record<string, string> = {
  cpi_yoy: '%',
  ppi_yoy: '%',
  pmi_manufacturing: '',
  pmi_non_manufacturing: '',
  m2_yoy: '%',
  social_financing: '亿',
  interest_rate_lpr_1y: '%',
};

/** 标签显示名。 */
export const REGIME_LABELS: Record<string, string> = {
  inflation_pressure: '通胀压力',
  monetary_stance: '货币立场',
  economic_momentum: '经济动能',
};

/** 格式化宏观指标值。 */
export function formatMacroValue(key: string, value: number | null): string {
  if (value == null) return '—';
  if (!Number.isFinite(value)) return '—';
  const unit = MACRO_UNITS[key] || '';
  if (key === 'social_financing') return `${(value / 10000).toFixed(0)}万${unit}`;
  if (unit === '%') return `${value.toFixed(1)}${unit}`;
  return `${value.toFixed(1)}${unit ? ' ' + unit : ''}`;
}

/** 标签 → badge variant。 */
export function regimeVariant(label: string): 'success' | 'destructive' | 'secondary' | 'outline' {
  if (label === 'low' || label === 'loose' || label === 'expanding') return 'success';
  if (label === 'high' || label === 'tight' || label === 'contracting') return 'destructive';
  if (label === 'moderate' || label === 'neutral' || label === 'stable') return 'secondary';
  return 'outline';
}

/** 标签 → 中文。 */
export function regimeChinese(label: string): string {
  const map: Record<string, string> = {
    low: '低', moderate: '适中', high: '高', unknown: '未知',
    loose: '宽松', neutral: '中性', tight: '收紧',
    expanding: '扩张', stable: '平稳', contracting: '收缩',
  };
  return map[label] || label;
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
      /* non-JSON */
    }
    throw new Error(`${label} failed: ${detail}`);
  }
  return (await res.json()) as T;
}

export const macroApi = {
  /** 获取最新宏观快照 (GET)。 */
  async fetch(): Promise<MacroSnapshot> {
    const res = await authFetch(`${API_BASE_URL}/api/screening/macro-snapshot`);
    return _jsonOrThrow<MacroSnapshot>(res, 'macro-snapshot');
  },
};
