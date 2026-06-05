/**
 * LLM Metrics API service -- fetches cost/latency summaries from the backend.
 */

import { authFetch } from './auth-api';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// ---- Types ----

export interface LLMMetricsTotals {
  calls: number;
  successes: number;
  errors: number;
  total_duration_ms: number;
  avg_duration_ms: number;
  prompt_chars: number;
  response_chars: number;
  sessions_scanned: number;
}

export interface AgentMetrics {
  agent_name: string;
  calls: number;
  successes: number;
  errors: number;
  avg_duration_ms: number;
  p95_duration_ms: number;
  total_duration_ms: number;
  prompt_chars: number;
  response_chars: number;
}

export interface DailyMetrics {
  date: string;
  calls: number;
  successes: number;
  avg_duration_ms: number;
  total_duration_ms: number;
}

export interface LLMMetricsSummary {
  totals: LLMMetricsTotals;
  agents: AgentMetrics[];
  daily_trend: DailyMetrics[];
  lookback_days: number;
}

// ---- API ----

export async function fetchLLMMetricsSummary(days: number = 7): Promise<LLMMetricsSummary> {
  const response = await authFetch(`${API_BASE_URL}/llm-metrics/summary?days=${days}`);
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  return response.json();
}
