import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

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
    dual_target_overview: {
      target_mode_counts: { dual_target: 4, research_only: 2 },
      dual_target_trade_date_count: 4,
      selection_target_count: 12,
      research_target_count: 12,
      short_trade_target_count: 12,
      research_selected_count: 4,
      research_near_miss_count: 3,
      research_rejected_count: 5,
      short_trade_selected_count: 3,
      short_trade_near_miss_count: 2,
      short_trade_blocked_count: 4,
      short_trade_rejected_count: 3,
      shell_target_count: 0,
      delta_classification_counts: { research_reject_short_pass: 2 },
      dominant_delta_reasons: ['short trade target promoted a setup that research pipeline kept as near-miss'],
      dominant_delta_reason_counts: { 'short trade target promoted a setup that research pipeline kept as near-miss': 1 },
      representative_cases: [
        {
          trade_date: '2026-03-20',
          ticker: '002916',
          delta_classification: 'research_reject_short_pass',
          research_decision: 'near_miss',
          short_trade_decision: 'selected',
          delta_summary: ['short trade target promoted a setup that research pipeline kept as near-miss'],
        },
      ],
    },
    feedback_summary: null,
    btst_followup_overview: {
      available: true,
      trade_date: '2026-03-23',
      next_trade_date: '2026-03-24',
      selection_target: 'short_trade_only',
      primary_entry_ticker: '300757',
      watchlist_tickers: ['601869'],
      excluded_research_tickers: ['002001', '300724'],
      selected_count: 1,
      watchlist_count: 1,
      excluded_research_count: 2,
      artifacts: {
        brief_json: '/tmp/reports/paper_trading_window_demo/btst_next_day_trade_brief_latest.json',
        execution_card_markdown: '/tmp/reports/paper_trading_window_demo/btst_premarket_execution_card_latest.md',
      },
    },
    btst_control_tower_overview: {
      available: true,
      generated_at: '2026-03-31T08:19:55',
      comparison_basis: 'nightly_history',
      overall_delta_verdict: 'changed',
      operator_focus: ['replay cohort 变化: report_count +1, short_trade_only +1。'],
      current_reference: {
        report_dir: 'data/reports/paper_trading_window_demo',
        report_name: 'paper_trading_window_demo',
        selection_target: 'short_trade_only',
        trade_date: '2026-03-23',
        next_trade_date: '2026-03-24',
      },
      previous_reference: {
        report_dir: 'data/reports/paper_trading_window_demo_prev',
        report_name: 'paper_trading_window_demo_prev',
        selection_target: 'short_trade_only',
        trade_date: '2026-03-20',
        next_trade_date: '2026-03-21',
      },
      selected_report_matches_current_reference: true,
      priority_has_changes: false,
      governance_has_changes: false,
      replay_has_changes: true,
      governance_overall_verdict: 'pass_with_warnings',
      recommendation: '保持 near-miss 观察，不做直接升格。',
      waiting_lane_count: 2,
      ready_lane_count: 1,
      lane_status_counts: {
        continue_controlled_roll_forward: 1,
        shadow_only_until_second_window: 1,
      },
      refresh_status: {
        candidate_entry_shadow_refresh: 'refreshed',
        btst_governance_synthesis_refresh: 'refreshed',
      },
      closed_frontiers: [
        {
          frontier_id: 'broad_penalty_relief',
          status: 'broad_penalty_route_closed_current_window',
          headline: 'broad stale/extension penalty relief 已被当前窗口证伪。',
          best_variant_name: 'nm_0.42__avoid_0.12__stale_0.08__ext_0.02',
          passing_variant_count: 0,
          best_variant_released_tickers: ['300724'],
          best_variant_focus_released_tickers: [],
        },
      ],
      rollout_lane_rows: [
        {
          lane_id: 'structural_shadow_hold_only',
          ticker: '300724',
          governance_tier: 'structural_shadow_hold_only',
          lane_status: 'structural_shadow_hold_only',
          action_tier: 'hold_only',
          blocker: 'post_release_quality_negative',
          validation_verdict: 'hold',
          missing_window_count: 1,
          next_step: '继续结构化 shadow 观察。',
          evidence_highlights: ['cases 2', 'missing windows 1', 'freeze negative'],
          context_reference: {
            report_name: 'paper_trading_window_demo',
            trade_date: '2026-03-23',
            symbol: '300724',
            selection_target: 'short_trade_only',
          },
        },
      ],
      next_actions: [
        {
          task_id: '300724_structural_shadow_hold_only',
          title: '维持 300724 structural shadow',
          why_now: 'post-release 质量未修复。',
          next_step: '继续结构化 shadow 观察。',
          source: 'p3_action_board',
          context_reference: {
            report_name: 'paper_trading_window_demo',
            trade_date: '2026-03-23',
            symbol: '300724',
            selection_target: 'short_trade_only',
          },
        },
      ],
      artifacts: {
        open_ready_delta_json: '/tmp/reports/btst_open_ready_delta_latest.json',
        nightly_control_tower_json: '/tmp/reports/btst_nightly_control_tower_latest.json',
        report_manifest_json: '/tmp/reports/report_manifest_latest.json',
      },
    },
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
        focusedSymbol="002916"
        selectedTradeDate="2026-03-23"
        tradeDateFilterCoverageText="1 / 6 trade dates"
        visibleFeedbackActivityCount={1}
        visibleWorkflowQueueCount={1}
        totalWorkflowQueueCount={2}
        onOpenContext={() => {}}
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
    expect(screen.queryByText('high_quality_selection')).not.toBeInTheDocument();
    expect(screen.queryByText('clear thesis')).not.toBeInTheDocument();
    expect(screen.getByText('reuse confirmed | disk +6')).toBeInTheDocument();
    expect(screen.getByText('Dual Target Overview')).toBeInTheDocument();
    expect(screen.getByText('4 dual-target days')).toBeInTheDocument();
    expect(screen.getByText('modes dual_target:4 | research_only:2')).toBeInTheDocument();
    expect(screen.getByText('Workspace Focus')).toBeInTheDocument();
    expect(screen.getByText('trade date 2026-03-23 | symbol 002916')).toBeInTheDocument();
    expect(screen.getByText('trade date filter 1 / 6 trade dates')).toBeInTheDocument();
    expect(screen.getByText('activity 1/2 | queue 1/2')).toBeInTheDocument();
    expect(screen.getByText('Dual Target Inspector')).toBeInTheDocument();
    expect(screen.getAllByText('BTST Follow-Up').length).toBeGreaterThan(0);
    expect(screen.getAllByText('BTST 控制塔').length).toBeGreaterThan(0);
    expect(screen.getByText('有变化 | 回放')).toBeInTheDocument();
    expect(screen.getAllByText('paper_trading_window_demo').length).toBeGreaterThan(0);
    expect(screen.getByText('当前报告已对齐最新运行')).toBeInTheDocument();
    expect(screen.getByText('已关闭路线')).toBeInTheDocument();
    expect(screen.getByText('广义 stale/extension 惩罚放松')).toBeInTheDocument();
    expect(screen.getByText('当前窗口已关闭')).toBeInTheDocument();
    expect(screen.getByText('执行车道')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '打开当前 BTST 运行' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '打开回放 300724' })).toBeInTheDocument();
    expect(screen.getByText('replay cohort 变化: report_count +1, short_trade_only +1。')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '查看产物' }).length).toBeGreaterThan(0);
    expect(screen.getAllByText('300757').length).toBeGreaterThan(0);
    expect(screen.getByText('watch 601869 | excluded 002001, 300724')).toBeInTheDocument();
    expect(screen.getByText('2026-03-20 002916:research_reject_short_pass | short trade target promoted a setup that research pipeline kept as near-miss')).toBeInTheDocument();
    expect(screen.getByText('selection_snapshot.json')).toBeInTheDocument();
    expect(screen.getByText('selection_review.md')).toBeInTheDocument();
    expect(screen.getByText('research_feedback.jsonl')).toBeInTheDocument();
    expect(screen.getByText('btst_next_day_trade_brief_latest.json')).toBeInTheDocument();
    expect(screen.getByText('position_blocked_score x1')).toBeInTheDocument();
    expect(screen.getByText('below_fast_score_threshold x3')).toBeInTheDocument();
  });

  it('filters activity sections by focused symbol and opens context from inspector cards', async () => {
    const user = userEvent.setup();
    const onOpenContext = vi.fn();

    render(
      <ReplayArtifactsInspector
        detail={detail}
        selectionArtifactDetail={selectionArtifactDetail}
        feedbackActivity={feedbackActivity}
        focusedSymbol="002916"
        selectedTradeDate="2026-03-23"
        tradeDateFilterCoverageText="1 / 6 trade dates"
        visibleFeedbackActivityCount={1}
        visibleWorkflowQueueCount={1}
        totalWorkflowQueueCount={2}
        onOpenContext={onOpenContext}
        isDetailLoading={false}
        isActivityLoading={false}
      />,
    );

    expect(screen.getByText('near miss sample')).toBeInTheDocument();
    expect(screen.queryByText('clear thesis')).not.toBeInTheDocument();

    await user.click(screen.getAllByRole('button', { name: 'Open Context' })[0]);

    expect(onOpenContext).toHaveBeenCalledWith({
      reportName: 'paper_trading_window_demo',
      tradeDate: '2026-03-20',
      symbol: '002916',
    });
  });

  it('opens replay context from BTST rollout lane cards', async () => {
    const user = userEvent.setup();
    const onOpenContext = vi.fn();

    render(
      <ReplayArtifactsInspector
        detail={detail}
        selectionArtifactDetail={selectionArtifactDetail}
        feedbackActivity={feedbackActivity}
        focusedSymbol="002916"
        selectedTradeDate="2026-03-23"
        tradeDateFilterCoverageText="1 / 6 trade dates"
        visibleFeedbackActivityCount={1}
        visibleWorkflowQueueCount={1}
        totalWorkflowQueueCount={2}
        onOpenContext={onOpenContext}
        isDetailLoading={false}
        isActivityLoading={false}
      />,
    );

    await user.click(screen.getByRole('button', { name: '打开回放 300724' }));

    expect(onOpenContext).toHaveBeenCalledWith({
      reportName: 'paper_trading_window_demo',
      tradeDate: '2026-03-23',
      symbol: '300724',
    });
  });
});