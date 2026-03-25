import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const { listMock, getMock, getSelectionArtifactDayMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  getMock: vi.fn(),
  getSelectionArtifactDayMock: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

vi.mock('@/services/replay-artifact-api', async () => {
  const actual = await vi.importActual<typeof import('@/services/replay-artifact-api')>('@/services/replay-artifact-api');
  return {
    ...actual,
    replayArtifactApi: {
      list: listMock,
      get: getMock,
      getSelectionArtifactDay: getSelectionArtifactDayMock,
      appendSelectionFeedback: vi.fn(),
    },
  };
});

import { ReplayArtifactsSettings } from '@/components/settings/replay-artifacts';
import type { ReplayArtifactDetail, ReplayArtifactSummary, ReplaySelectionArtifactDay } from '@/services/replay-artifact-api';

const reports: ReplayArtifactSummary[] = [
  {
    report_dir: 'paper_trading_window_recent',
    window: { start_date: '2026-03-16', end_date: '2026-03-23' },
    run_header: {
      mode: 'paper',
      plan_generation_mode: 'live_pipeline',
      model_provider: 'MiniMax',
      model_name: 'MiniMax-M2.7',
    },
    headline_kpi: {
      initial_capital: 100000,
      final_value: 101000,
      total_return_pct: 1.0,
      sharpe_ratio: 1.1,
      sortino_ratio: 1.2,
      max_drawdown_pct: -1.5,
      max_drawdown_date: '2026-03-20',
      executed_trade_days: 4,
      total_executed_orders: 6,
    },
    deployment_funnel_runtime: {
      avg_invested_ratio: 0.3,
      peak_invested_ratio: 0.4,
      avg_layer_b_count: 5,
      avg_watchlist_count: 1,
      avg_buy_order_count: 1,
      top_buy_blockers: [],
      top_watchlist_blockers: [],
      avg_total_day_seconds: 10,
      avg_post_market_seconds: 6,
    },
    artifacts: {},
    cache_benchmark_overview: {
      requested: false,
      executed: false,
      write_status: null,
      reason: null,
      ticker: null,
      trade_date: null,
      reuse_confirmed: null,
      disk_hit_gain: null,
      miss_reduction: null,
      set_reduction: null,
      first_hit_rate: null,
      second_hit_rate: null,
      artifacts: {},
    },
  },
  {
    report_dir: 'paper_trading_window_older',
    window: { start_date: '2026-03-09', end_date: '2026-03-13' },
    run_header: {
      mode: 'paper',
      plan_generation_mode: 'live_pipeline',
      model_provider: 'MiniMax',
      model_name: 'MiniMax-M2.5',
    },
    headline_kpi: {
      initial_capital: 100000,
      final_value: 99500,
      total_return_pct: -0.5,
      sharpe_ratio: 0.8,
      sortino_ratio: 0.9,
      max_drawdown_pct: -2.0,
      max_drawdown_date: '2026-03-11',
      executed_trade_days: 3,
      total_executed_orders: 4,
    },
    deployment_funnel_runtime: {
      avg_invested_ratio: 0.2,
      peak_invested_ratio: 0.3,
      avg_layer_b_count: 3,
      avg_watchlist_count: 1,
      avg_buy_order_count: 0,
      top_buy_blockers: [],
      top_watchlist_blockers: [],
      avg_total_day_seconds: 9,
      avg_post_market_seconds: 5,
    },
    artifacts: {},
    cache_benchmark_overview: {
      requested: false,
      executed: false,
      write_status: null,
      reason: null,
      ticker: null,
      trade_date: null,
      reuse_confirmed: null,
      disk_hit_gain: null,
      miss_reduction: null,
      set_reduction: null,
      first_hit_rate: null,
      second_hit_rate: null,
      artifacts: {},
    },
  },
];

const detail: ReplayArtifactDetail = {
  ...reports[0],
  ticker_execution_digest: [],
  final_portfolio_snapshot: {},
  selection_artifact_overview: {
    available: true,
    artifact_root: '/tmp/replay/selection_artifacts',
    trade_date_count: 1,
    available_trade_dates: ['2026-03-23'],
    write_status_counts: { success: 1 },
    blocker_counts: [],
    feedback_summary: null,
  },
};

const dayDetail: ReplaySelectionArtifactDay = {
  report_dir: 'paper_trading_window_recent',
  trade_date: '2026-03-23',
  paths: {
    snapshot_path: '/tmp/replay/selection_artifacts/2026-03-23/selection_snapshot.json',
    review_path: '/tmp/replay/selection_artifacts/2026-03-23/selection_review.md',
    feedback_path: '/tmp/replay/selection_artifacts/2026-03-23/research_feedback.jsonl',
  },
  snapshot: {
    artifact_version: 'v1',
    run_id: 'run-1',
    experiment_id: null,
    trade_date: '2026-03-23',
    market: 'CN',
    decision_timestamp: '2026-03-23T15:00:00+08:00',
    data_available_until: '2026-03-23T15:00:00+08:00',
    pipeline_config_snapshot: {},
    universe_summary: { watchlist_count: 0, buy_order_count: 0, high_pool_count: 0 },
    selected: [],
    rejected: [],
    buy_orders: [],
    sell_orders: [],
    funnel_diagnostics: {},
    artifact_status: {},
  },
  review_markdown: '# review',
  feedback_record_count: 0,
  feedback_records: [],
  feedback_summary: {
    label_version: 'v1',
    feedback_count: 0,
    final_feedback_count: 0,
    symbols: [],
    reviewers: [],
    primary_tag_counts: {},
    tag_counts: {},
    review_status_counts: {},
    verdict_counts: {},
    latest_created_at: null,
  },
  feedback_options: {
    allowed_tags: [],
    allowed_review_statuses: ['draft', 'final'],
  },
  blocker_counts: [],
};

describe('ReplayArtifactsSettings workspace defaults', () => {
  it('loads the first report from the report rail and fetches its latest trade date detail', async () => {
    listMock.mockResolvedValue(reports);
    getMock.mockResolvedValue(detail);
    getSelectionArtifactDayMock.mockResolvedValue(dayDetail);

    render(<ReplayArtifactsSettings mode="workspace" />);

    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith('paper_trading_window_recent');
    });

    await waitFor(() => {
      expect(getSelectionArtifactDayMock).toHaveBeenCalledWith('paper_trading_window_recent', '2026-03-23');
    });

    expect(screen.getAllByText('paper_trading_window_recent').length).toBeGreaterThan(0);
    expect(screen.getByText('1 trade dates')).toBeInTheDocument();
  });
});