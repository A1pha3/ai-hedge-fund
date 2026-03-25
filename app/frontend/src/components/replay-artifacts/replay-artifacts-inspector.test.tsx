import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ReplayArtifactsInspector } from '@/components/replay-artifacts/replay-artifacts-inspector';
import type { ReplayArtifactDetail, ReplaySelectionArtifactDay, ReplayFeedbackActivity } from '@/services/replay-artifact-api';

const detail: ReplayArtifactDetail = {
  report_dir: '/tmp/reports/paper_trading_window_demo',
  window: { start_date: '2026-03-16', end_date: '2026-03-23' },
  run_header: {
    mode: 'paper',
    plan_generation_mode: 'live_pipeline',
    model_provider: 'MiniMax',
    model_name: 'MiniMax-M2.7',
  },
  headline_kpi: {
    initial_capital: 100000,
    final_value: 101200,
    total_return_pct: 1.2,
    sharpe_ratio: 1.5,
    sortino_ratio: 1.8,
    max_drawdown_pct: -2.1,
    max_drawdown_date: '2026-03-20',
    executed_trade_days: 4,
    total_executed_orders: 6,
  },
  deployment_funnel_runtime: {
    avg_invested_ratio: 0.3,
    peak_invested_ratio: 0.42,
    avg_layer_b_count: 5.2,
    avg_watchlist_count: 1.4,
    avg_buy_order_count: 0.8,
    top_buy_blockers: [{ reason: 'position_blocked_score', count: 1 }],
    top_watchlist_blockers: [{ reason: 'below_fast_score_threshold', count: 3 }],
    avg_total_day_seconds: 11.2,
    avg_post_market_seconds: 7.3,
  },
  artifacts: {
    session_summary: '/tmp/reports/paper_trading_window_demo/session_summary.json',
    window_review: '/tmp/reports/paper_trading_window_demo/window_review.md',
  },
  cache_benchmark_overview: {
    requested: true,
    executed: true,
    write_status: 'success',
    reason: null,
    ticker: '300724',
    trade_date: '2026-03-23',
    reuse_confirmed: true,
    disk_hit_gain: 6,
    miss_reduction: 6,
    set_reduction: 6,
    first_hit_rate: 0,
    second_hit_rate: 1,
    artifacts: {},
  },
  ticker_execution_digest: [],
  final_portfolio_snapshot: {},
  selection_artifact_overview: {
    available: true,
    artifact_root: '/tmp/reports/paper_trading_window_demo/selection_artifacts',
    trade_date_count: 6,
    available_trade_dates: ['2026-03-23'],
    write_status_counts: { success: 6 },
    blocker_counts: [{ reason: 'position_blocked_score', count: 1 }],
    feedback_summary: null,
  },
};

const selectionArtifactDetail: ReplaySelectionArtifactDay = {
  report_dir: 'paper_trading_window_demo',
  trade_date: '2026-03-23',
  paths: {
    snapshot_path: '/tmp/reports/paper_trading_window_demo/selection_artifacts/2026-03-23/selection_snapshot.json',
    review_path: '/tmp/reports/paper_trading_window_demo/selection_artifacts/2026-03-23/selection_review.md',
    feedback_path: '/tmp/reports/paper_trading_window_demo/selection_artifacts/2026-03-23/research_feedback.jsonl',
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
    universe_summary: {},
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
    allowed_review_statuses: [],
  },
  blocker_counts: [{ reason: 'position_blocked_score', count: 1 }],
};

const feedbackActivity: ReplayFeedbackActivity = {
  report_name: 'paper_trading_window_demo',
  reviewer: null,
  limit: 8,
  record_count: 2,
  recent_records: [
    {
      report_name: 'paper_trading_window_demo',
      trade_date: '2026-03-23',
      symbol: '300724',
      review_scope: 'watchlist',
      reviewer: 'einstein',
      review_status: 'final',
      primary_tag: 'high_quality_selection',
      tags: ['high_quality_selection', 'thesis_clear'],
      confidence: 0.92,
      research_verdict: 'selected_for_good_reason',
      notes: 'clear thesis',
      created_at: '2026-03-23T11:00:00+08:00',
      feedback_path: '/tmp/reports/paper_trading_window_demo/selection_artifacts/2026-03-23/research_feedback.jsonl',
    },
    {
      report_name: 'paper_trading_window_demo',
      trade_date: '2026-03-20',
      symbol: '002916',
      review_scope: 'near_miss',
      reviewer: 'curie',
      review_status: 'draft',
      primary_tag: 'threshold_false_negative',
      tags: ['threshold_false_negative'],
      confidence: 0.61,
      research_verdict: 'needs_more_confirmation',
      notes: 'near miss sample',
      created_at: '2026-03-23T09:00:00+08:00',
      feedback_path: '/tmp/reports/paper_trading_window_demo/selection_artifacts/2026-03-20/research_feedback.jsonl',
    },
  ],
  review_status_counts: { final: 1, draft: 1 },
  tag_counts: { high_quality_selection: 1, thesis_clear: 1, threshold_false_negative: 1 },
  reviewer_counts: { einstein: 1, curie: 1 },
  report_counts: { paper_trading_window_demo: 2 },
  workflow_status_counts: { draft: 1, final: 1 },
  workflow_queue: {
    draft: [
      {
        report_name: 'paper_trading_window_demo',
        trade_date: '2026-03-20',
        symbol: '002916',
        review_scope: 'near_miss',
        reviewer: 'curie',
        review_status: 'draft',
        primary_tag: 'threshold_false_negative',
        tags: ['threshold_false_negative'],
        confidence: 0.61,
        research_verdict: 'needs_more_confirmation',
        notes: 'near miss sample',
        created_at: '2026-03-23T09:00:00+08:00',
        feedback_path: '/tmp/reports/paper_trading_window_demo/selection_artifacts/2026-03-20/research_feedback.jsonl',
      },
    ],
    final: [
      {
        report_name: 'paper_trading_window_demo',
        trade_date: '2026-03-23',
        symbol: '300724',
        review_scope: 'watchlist',
        reviewer: 'einstein',
        review_status: 'final',
        primary_tag: 'high_quality_selection',
        tags: ['high_quality_selection', 'thesis_clear'],
        confidence: 0.92,
        research_verdict: 'selected_for_good_reason',
        notes: 'clear thesis',
        created_at: '2026-03-23T11:00:00+08:00',
        feedback_path: '/tmp/reports/paper_trading_window_demo/selection_artifacts/2026-03-23/research_feedback.jsonl',
      },
    ],
    adjudicated: [],
  },
};

describe('ReplayArtifactsInspector', () => {
  it('renders workspace inspector summaries and leaf file names', () => {
    render(
      <ReplayArtifactsInspector
        detail={detail}
        selectionArtifactDetail={selectionArtifactDetail}
        feedbackActivity={feedbackActivity}
        isDetailLoading={false}
        isActivityLoading={false}
      />,
    );

    expect(screen.getByText('Inspector')).toBeInTheDocument();
    expect(screen.getByText('Feedback Activity')).toBeInTheDocument();
    expect(screen.getByText('2 recent records')).toBeInTheDocument();
    expect(screen.getByText('status final:1 | draft:1')).toBeInTheDocument();
    expect(screen.getByText('draft:1 | final:1')).toBeInTheDocument();
    expect(screen.getByText('Pending Draft Queue')).toBeInTheDocument();
    expect(screen.getByText('near miss sample')).toBeInTheDocument();
    expect(screen.getByText('high_quality_selection')).toBeInTheDocument();
    expect(screen.getByText('clear thesis')).toBeInTheDocument();
    expect(screen.getByText('reuse confirmed | disk +6')).toBeInTheDocument();
    expect(screen.getByText('selection_snapshot.json')).toBeInTheDocument();
    expect(screen.getByText('selection_review.md')).toBeInTheDocument();
    expect(screen.getByText('research_feedback.jsonl')).toBeInTheDocument();
    expect(screen.getByText('position_blocked_score x1')).toBeInTheDocument();
    expect(screen.getByText('below_fast_score_threshold x3')).toBeInTheDocument();
  });
});