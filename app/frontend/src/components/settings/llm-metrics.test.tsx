import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockFetch = vi.fn();

vi.mock('@/services/llm-metrics-api', () => ({
  fetchLLMMetricsSummary: (...args: unknown[]) => mockFetch(...args),
}));

vi.mock('@/services/auth-api', () => ({
  authFetch: vi.fn(),
  authHeaders: vi.fn(() => ({})),
  clearStoredToken: vi.fn(),
}));

import { LLMMetricsPanel } from '@/components/settings/llm-metrics';

const SAMPLE_SUMMARY = {
  totals: {
    calls: 120,
    successes: 115,
    errors: 5,
    total_duration_ms: 180000,
    avg_duration_ms: 1500,
    prompt_chars: 360000,
    response_chars: 72000,
    sessions_scanned: 3,
  },
  agents: [
    {
      agent_name: 'warren_buffett_agent',
      calls: 30,
      successes: 30,
      errors: 0,
      avg_duration_ms: 1200,
      p95_duration_ms: 2100,
      total_duration_ms: 36000,
      prompt_chars: 90000,
      response_chars: 18000,
    },
    {
      agent_name: 'cathie_wood_agent',
      calls: 25,
      successes: 20,
      errors: 5,
      avg_duration_ms: 2000,
      p95_duration_ms: 3500,
      total_duration_ms: 50000,
      prompt_chars: 75000,
      response_chars: 15000,
    },
  ],
  daily_trend: [
    { date: '2026-06-04', calls: 40, successes: 40, avg_duration_ms: 1400, total_duration_ms: 56000 },
    { date: '2026-06-05', calls: 45, successes: 40, avg_duration_ms: 1600, total_duration_ms: 72000 },
    { date: '2026-06-06', calls: 35, successes: 35, avg_duration_ms: 1300, total_duration_ms: 45500 },
  ],
  lookback_days: 7,
};

describe('LLMMetricsPanel', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it('shows empty state when no data is available', async () => {
    mockFetch.mockResolvedValue({
      totals: { calls: 0, successes: 0, errors: 0, total_duration_ms: 0, avg_duration_ms: 0, prompt_chars: 0, response_chars: 0, sessions_scanned: 0 },
      agents: [],
      daily_trend: [],
      lookback_days: 7,
    });

    render(<LLMMetricsPanel />);

    await waitFor(() => {
      expect(screen.getByText(/No LLM metrics data available/i)).toBeInTheDocument();
    });
  });

  it('renders summary cards with aggregated data', async () => {
    mockFetch.mockResolvedValue(SAMPLE_SUMMARY);

    render(<LLMMetricsPanel />);

    await waitFor(() => {
      expect(screen.getByText('120')).toBeInTheDocument();
    });

    expect(screen.getByText(/1\.5s/)).toBeInTheDocument();
    expect(screen.getByText('4.2%')).toBeInTheDocument();
  });

  it('renders agent rows in heatmap grids', async () => {
    mockFetch.mockResolvedValue(SAMPLE_SUMMARY);

    render(<LLMMetricsPanel />);

    // Agent names appear in multiple heatmap grids (avg, P95, calls), so use getAllByText
    await waitFor(() => {
      expect(screen.getAllByText(/warren buffett/i).length).toBeGreaterThanOrEqual(3);
    });

    expect(screen.getAllByText(/cathie wood/i).length).toBeGreaterThanOrEqual(3);
  });

  it('renders daily trend section', async () => {
    mockFetch.mockResolvedValue(SAMPLE_SUMMARY);

    render(<LLMMetricsPanel />);

    await waitFor(() => {
      expect(screen.getByText('Daily Trend')).toBeInTheDocument();
    });

    // Date labels (MM-DD format, sliced from position 5)
    expect(screen.getByText('06-04')).toBeInTheDocument();
    expect(screen.getByText('06-05')).toBeInTheDocument();
    expect(screen.getByText('06-06')).toBeInTheDocument();
  });

  it('shows error state on fetch failure', async () => {
    mockFetch.mockRejectedValue(new Error('Network error'));

    render(<LLMMetricsPanel />);

    await waitFor(() => {
      expect(screen.getByText(/Error: Network error/i)).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// P2 6.4: Heatmap / cost-savings / daily-provider panel tests
// ---------------------------------------------------------------------------

import type { LLMMetricsSummary } from '@/services/llm-metrics-api';

function _makeSummaryWithHeatmap(overrides: Partial<LLMMetricsSummary> = {}): LLMMetricsSummary {
  return {
    totals: {
      calls: 100,
      successes: 95,
      errors: 5,
      total_duration_ms: 150000,
      avg_duration_ms: 1500,
      prompt_chars: 200000,
      response_chars: 50000,
      sessions_scanned: 2,
      estimated_cost_usd: 1.2345,
    },
    agents: [
      {
        agent_name: 'warren_buffett_agent',
        calls: 50,
        successes: 50,
        errors: 0,
        avg_duration_ms: 1500,
        p95_duration_ms: 1800,
        total_duration_ms: 75000,
        prompt_chars: 100000,
        response_chars: 25000,
        estimated_cost_usd: 1.0,
      },
      {
        agent_name: 'charlie_munger_agent',
        calls: 50,
        successes: 45,
        errors: 5,
        avg_duration_ms: 1500,
        p95_duration_ms: 1800,
        total_duration_ms: 75000,
        prompt_chars: 100000,
        response_chars: 25000,
        estimated_cost_usd: 0.2345,
      },
    ],
    daily_trend: [
      { date: '2026-06-01', calls: 50, successes: 47, avg_duration_ms: 1500, total_duration_ms: 75000 },
      { date: '2026-06-02', calls: 50, successes: 48, avg_duration_ms: 1500, total_duration_ms: 75000 },
    ],
    lookback_days: 7,
    providers: [
      {
        provider: 'openai',
        calls: 60,
        successes: 58,
        errors: 2,
        error_rate: 0.0333,
        avg_duration_ms: 1400,
        p95_duration_ms: 1800,
        total_duration_ms: 84000,
        estimated_cost_usd: 0.85,
      },
      {
        provider: 'anthropic',
        calls: 30,
        successes: 28,
        errors: 2,
        error_rate: 0.0667,
        avg_duration_ms: 1700,
        p95_duration_ms: 2000,
        total_duration_ms: 51000,
        estimated_cost_usd: 0.30,
      },
      {
        provider: 'deepseek',
        calls: 10,
        successes: 9,
        errors: 1,
        error_rate: 0.10,
        avg_duration_ms: 700,
        p95_duration_ms: 900,
        total_duration_ms: 7000,
        estimated_cost_usd: 0.0845,
      },
    ],
    daily_provider: [
      {
        date: '2026-06-01',
        providers: [
          { provider: 'openai', calls: 30, errors: 1, error_rate: 0.0333, estimated_cost_usd: 0.4 },
          { provider: 'anthropic', calls: 15, errors: 1, error_rate: 0.0667, estimated_cost_usd: 0.15 },
          { provider: 'deepseek', calls: 5, errors: 0, error_rate: 0.0, estimated_cost_usd: 0.05 },
        ],
      },
      {
        date: '2026-06-02',
        providers: [
          { provider: 'openai', calls: 30, errors: 1, error_rate: 0.0333, estimated_cost_usd: 0.45 },
          // anthropic and deepseek did not run on day 2 — should render as "·"
        ],
      },
    ],
    top_agents_by_cost: [
      {
        agent_name: 'warren_buffett_agent',
        calls: 50,
        successes: 50,
        errors: 0,
        avg_duration_ms: 1500,
        p95_duration_ms: 1800,
        total_duration_ms: 75000,
        prompt_chars: 100000,
        response_chars: 25000,
        estimated_cost_usd: 1.0,
      },
      {
        agent_name: 'charlie_munger_agent',
        calls: 50,
        successes: 45,
        errors: 5,
        avg_duration_ms: 1500,
        p95_duration_ms: 1800,
        total_duration_ms: 75000,
        prompt_chars: 100000,
        response_chars: 25000,
        estimated_cost_usd: 0.2345,
      },
    ],
    top_providers_by_latency: [
      {
        provider: 'anthropic',
        calls: 30,
        successes: 28,
        errors: 2,
        error_rate: 0.0667,
        avg_duration_ms: 1700,
        p95_duration_ms: 2000,
        total_duration_ms: 51000,
        estimated_cost_usd: 0.30,
      },
      {
        provider: 'openai',
        calls: 60,
        successes: 58,
        errors: 2,
        error_rate: 0.0333,
        avg_duration_ms: 1400,
        p95_duration_ms: 1800,
        total_duration_ms: 84000,
        estimated_cost_usd: 0.85,
      },
      {
        provider: 'deepseek',
        calls: 10,
        successes: 9,
        errors: 1,
        error_rate: 0.10,
        avg_duration_ms: 700,
        p95_duration_ms: 900,
        total_duration_ms: 7000,
        estimated_cost_usd: 0.0845,
      },
    ],
    cost_savings_suggestions: [
      {
        agent_name: 'warren_buffett_agent',
        current_cost_per_call: 0.02,
        median_cost_per_call: 0.005,
        potential_savings_pct: 75,
        calls: 50,
      },
    ],
    ...overrides,
  };
}

describe('LLMMetricsPanel P2 6.4 (heatmaps + cost savings)', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it('renders the provider cost & latency panels when providers are returned', async () => {
    mockFetch.mockResolvedValue(_makeSummaryWithHeatmap());
    render(<LLMMetricsPanel />);
    await waitFor(() => {
      expect(screen.getByTestId('provider-cost-latency-panels')).toBeInTheDocument();
    });
    // All 3 providers are rendered as cost rows
    const rows = screen.getAllByTestId('provider-cost-row');
    expect(rows).toHaveLength(3);
  });

  it('renders the top slowest providers panel sorted by latency desc', async () => {
    mockFetch.mockResolvedValue(_makeSummaryWithHeatmap());
    render(<LLMMetricsPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId('slow-provider-row')).toHaveLength(3);
    });
    const slowRows = screen.getAllByTestId('slow-provider-row');
    expect(slowRows[0].getAttribute('data-provider')).toBe('anthropic'); // 1700ms
    expect(slowRows[1].getAttribute('data-provider')).toBe('openai');    // 1400ms
    expect(slowRows[2].getAttribute('data-provider')).toBe('deepseek');   // 700ms
  });

  it('renders the top expensive agents panel', async () => {
    mockFetch.mockResolvedValue(_makeSummaryWithHeatmap());
    render(<LLMMetricsPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId('expensive-agent-row')).toHaveLength(2);
    });
    const agentRows = screen.getAllByTestId('expensive-agent-row');
    expect(agentRows[0].getAttribute('data-agent')).toBe('warren_buffett_agent');
    expect(agentRows[1].getAttribute('data-agent')).toBe('charlie_munger_agent');
  });

  it('renders cost-savings suggestions with the agent name and savings pct', async () => {
    mockFetch.mockResolvedValue(_makeSummaryWithHeatmap());
    render(<LLMMetricsPanel />);
    await waitFor(() => {
      expect(screen.getByTestId('cost-savings-suggestions')).toBeInTheDocument();
    });
    const suggestions = screen.getAllByTestId('cost-savings-suggestion');
    expect(suggestions).toHaveLength(1);
    expect(suggestions[0].textContent).toContain('warren_buffett_agent');
    expect(suggestions[0].textContent).toContain('可省 75%');
  });

  it('omits the cost-savings card when there are no suggestions', async () => {
    const summary = _makeSummaryWithHeatmap();
    summary.cost_savings_suggestions = [];
    mockFetch.mockResolvedValue(summary);
    render(<LLMMetricsPanel />);
    await waitFor(() => {
      expect(screen.getByTestId('provider-cost-latency-panels')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('cost-savings-suggestions')).not.toBeInTheDocument();
  });

  it('renders the daily provider heatmap with one row per provider', async () => {
    mockFetch.mockResolvedValue(_makeSummaryWithHeatmap());
    render(<LLMMetricsPanel />);
    await waitFor(() => {
      expect(screen.getByTestId('daily-provider-heatmap')).toBeInTheDocument();
    });
    const heatRows = screen.getAllByTestId('heatmap-row');
    // 3 distinct providers in the test data, sorted alphabetically
    expect(heatRows).toHaveLength(3);
    const providerAttrs = heatRows.map(r => r.getAttribute('data-provider'));
    expect(providerAttrs).toEqual(['anthropic', 'deepseek', 'openai']);
  });

  it('omits the heatmap panels when providers are absent', async () => {
    const summary = _makeSummaryWithHeatmap();
    summary.providers = [];
    summary.top_agents_by_cost = [];
    summary.top_providers_by_latency = [];
    summary.daily_provider = [];
    summary.cost_savings_suggestions = [];
    mockFetch.mockResolvedValue(summary);
    render(<LLMMetricsPanel />);
    await waitFor(() => {
      // The component still renders the agent heatmap; we just verify
      // our new panels are NOT shown.
      expect(screen.queryByTestId('provider-cost-latency-panels')).not.toBeInTheDocument();
    });
    expect(screen.queryByTestId('cost-savings-suggestions')).not.toBeInTheDocument();
    expect(screen.queryByTestId('daily-provider-heatmap')).not.toBeInTheDocument();
  });
});
