/**
 * Portfolio return attribution API client.
 * GET/POST /api/portfolio/attribution — Brinson model decomposition.
 */

const API_BASE = "/api/portfolio";

export interface TickerAttribution {
  ticker: string;
  portfolio_weight: number;
  benchmark_weight: number;
  portfolio_return: number;
  benchmark_return: number;
  allocation_contribution: number;
  selection_contribution: number;
  total_contribution: number;
}

export interface AttributionResponse {
  start_date: string;
  end_date: string;
  total_portfolio_return: number;
  total_benchmark_return: number;
  total_allocation_contribution: number;
  total_selection_contribution: number;
  total_residual: number;
  tickers: TickerAttribution[];
}

export interface AttributionRequest {
  ticker_returns: Record<string, number>;
  ticker_market_values: Record<string, number>;
  total_portfolio_value: number;
  benchmark_weights?: Record<string, number> | null;
  benchmark_returns?: Record<string, number> | null;
  start_date: string;
  end_date: string;
}

/**
 * Fetch Brinson attribution via POST (JSON body).
 */
export async function fetchAttribution(
  payload: AttributionRequest,
): Promise<AttributionResponse> {
  const res = await fetch(`${API_BASE}/attribution`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Attribution API error: ${detail}`);
  }

  return res.json();
}

/**
 * Fetch attribution via GET (query params for simple cases).
 */
export async function fetchAttributionGet(params: {
  start: string;
  end: string;
  tickers: string;
  returns: string;
  weights: string;
  total_value: number;
  benchmark_weights?: string;
  benchmark_returns?: string;
}): Promise<AttributionResponse> {
  const qs = new URLSearchParams({
    start: params.start,
    end: params.end,
    tickers: params.tickers,
    returns: params.returns,
    weights: params.weights,
    total_value: String(params.total_value),
  });
  if (params.benchmark_weights) qs.set("benchmark_weights_csv", params.benchmark_weights);
  if (params.benchmark_returns) qs.set("benchmark_returns_csv", params.benchmark_returns);

  const res = await fetch(`${API_BASE}/attribution?${qs}`);

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Attribution API error: ${detail}`);
  }

  return res.json();
}
