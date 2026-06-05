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
