/**
 * Lookback Audit API service (NEW-B P0) — fetches the per-ticker historical
 * audit produced by the backend's GET /research/lookback-audit endpoint.
 *
 * The endpoint takes a trade date and looks forward N days to compare the
 * strategy's selection at that date with the realized price action. This
 * service wraps the call so the frontend can render a per-ticker hit-rate
 * dashboard without duplicating the request construction.
 */

import { authFetch } from './auth-api';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface TickerAuditResult {
  ticker: string;
  rank: number;
  score_final: number;
  entry_date: string;
  entry_price: number | null;
  exit_date: string | null;
  exit_price: number | null;
  return_pct: number | null;
  max_drawdown_pct: number | null;
  max_return_pct: number | null;
  trading_days_held: number;
  data_status: string;
}

export interface LookbackAuditSummary {
  hit_rate?: number;
  avg_return_pct?: number;
  best_return_pct?: number;
  worst_return_pct?: number;
  median_return_pct?: number;
  [key: string]: number | string | undefined;
}

export interface LookbackAuditResponse {
  audit_date: string;
  lookforward_days: number;
  selected_count: number;
  audited_count: number;
  ticker_results: TickerAuditResult[];
  summary: LookbackAuditSummary;
}

export interface LookbackAuditError {
  error: string;
  audit_date: string;
  lookforward_days: number;
}

function normalizeDate(date: string): string {
  const trimmed = (date || '').trim();
  if (trimmed.length === 10 && trimmed[4] === '-' && trimmed[7] === '-') {
    return trimmed.replace(/-/g, '');
  }
  return trimmed;
}

export async function fetchLookbackAudit(params: {
  date: string;
  days?: number;
  topN?: number;
  signal?: AbortSignal;
}): Promise<LookbackAuditResponse> {
  const date = normalizeDate(params.date);
  const days = params.days ?? 30;
  const topN = params.topN ?? 10;
  const url = `${API_BASE_URL}/research/lookback-audit?date=${encodeURIComponent(
    date,
  )}&days=${days}&top_n=${topN}`;
  const res = await authFetch(url, { signal: params.signal });
  if (!res.ok) {
    // The endpoint may return a structured error body; surface it as text
    const detail = await res.text();
    throw new Error(`Lookback audit ${res.status}: ${detail || res.statusText}`);
  }
  const json = (await res.json()) as LookbackAuditResponse | LookbackAuditError;
  if ('error' in json) {
    throw new Error(json.error);
  }
  return json;
}
