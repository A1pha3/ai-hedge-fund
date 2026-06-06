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
  estimated_cost_usd?: number;
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
  estimated_cost_usd?: number;
}

export interface ProviderMetrics {
  provider: string;
  calls: number;
  successes: number;
  errors: number;
  error_rate: number;
  avg_duration_ms: number;
  p95_duration_ms: number;
  total_duration_ms: number;
  estimated_cost_usd?: number;
}

export interface DailyProviderEntry {
  provider: string;
  calls: number;
  errors: number;
  error_rate: number;
  estimated_cost_usd: number;
}

export interface DailyProviderAggregate {
  date: string;
  providers: DailyProviderEntry[];
}

export interface CostSavingsSuggestion {
  agent_name: string;
  current_cost_per_call: number;
  median_cost_per_call: number;
  potential_savings_pct: number;
  calls: number;
}

export interface DailyMetrics {
  date: string;
  calls: number;
  successes: number;
  avg_duration_ms: number;
  total_duration_ms: number;
  estimated_cost_usd?: number;
}

export interface LLMMetricsSummary {
  totals: LLMMetricsTotals;
  agents: AgentMetrics[];
  providers?: ProviderMetrics[];
  daily_trend: DailyMetrics[];
  daily_provider?: DailyProviderAggregate[];
  top_agents_by_cost?: AgentMetrics[];
  top_providers_by_latency?: ProviderMetrics[];
  cost_savings_suggestions?: CostSavingsSuggestion[];
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
