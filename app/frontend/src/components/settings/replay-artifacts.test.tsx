import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { listMock, getMock, getSelectionArtifactDayMock, appendSelectionFeedbackMock, appendSelectionFeedbackBatchMock, getFeedbackActivityMock, getWorkflowQueueMock, updateWorkflowQueueItemMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  getMock: vi.fn(),
  getSelectionArtifactDayMock: vi.fn(),
  appendSelectionFeedbackMock: vi.fn(),
  appendSelectionFeedbackBatchMock: vi.fn(),
  getFeedbackActivityMock: vi.fn(),
  getWorkflowQueueMock: vi.fn(),
  updateWorkflowQueueItemMock: vi.fn(),
}));

vi.mock('@/contexts/auth-context', () => ({
  useAuth: () => ({
    user: {
      id: 1,
      username: 'einstein',
      email: null,
      role: 'admin',
      created_at: null,
      updated_at: null,
    },
  }),
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
      appendSelectionFeedback: appendSelectionFeedbackMock,
      appendSelectionFeedbackBatch: appendSelectionFeedbackBatchMock,
      getFeedbackActivity: getFeedbackActivityMock,
      getWorkflowQueue: getWorkflowQueueMock,
      updateWorkflowQueueItem: updateWorkflowQueueItemMock,
    },
  };
});

import { ReplayArtifactsSettings } from '@/components/settings/replay-artifacts';
import type { ReplayArtifactDetail, ReplayArtifactSummary, ReplaySelectionArtifactDay } from '@/services/replay-artifact-api';

beforeEach(() => {
  listMock.mockReset();
  getMock.mockReset();
  getSelectionArtifactDayMock.mockReset();
  appendSelectionFeedbackMock.mockReset();
  appendSelectionFeedbackBatchMock.mockReset();
  getFeedbackActivityMock.mockReset();
  getWorkflowQueueMock.mockReset();
  updateWorkflowQueueItemMock.mockReset();
});

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
    selection_artifact_overview: {
      available: true,
      artifact_root: '/tmp/replay/selection_artifacts',
      trade_date_count: 1,
      available_trade_dates: ['2026-03-23'],
      trade_date_target_index: [
        {
          trade_date: '2026-03-23',
          target_mode: 'dual_target',
          short_trade_profile_name: 'default',
          delta_classification_counts: { research_reject_short_pass: 1 },
          research_selected_count: 1,
          research_near_miss_count: 1,
          short_trade_selected_count: 1,
          short_trade_blocked_count: 1,
        },
      ],
      write_status_counts: { success: 1 },
      blocker_counts: [],
      short_trade_profile_overview: {
        profile_name_counts: { default: 1 },
        latest_profile_name: 'default',
        latest_profile_trade_date: '2026-03-23',
        latest_profile_config: { select_threshold: 0.58 },
      },
      dual_target_overview: {
        target_mode_counts: { dual_target: 1 },
        dual_target_trade_date_count: 1,
        selection_target_count: 2,
        research_target_count: 2,
        short_trade_target_count: 2,
        research_selected_count: 1,
        research_near_miss_count: 1,
        research_rejected_count: 0,
        short_trade_selected_count: 1,
        short_trade_near_miss_count: 0,
        short_trade_blocked_count: 1,
        short_trade_rejected_count: 0,
        shell_target_count: 0,
        delta_classification_counts: { research_reject_short_pass: 1 },
        dominant_delta_reasons: ['short trade target promoted a setup that research pipeline kept as near-miss'],
        dominant_delta_reason_counts: { 'short trade target promoted a setup that research pipeline kept as near-miss': 1 },
        representative_cases: [
          {
            trade_date: '2026-03-23',
            ticker: '002916',
            delta_classification: 'research_reject_short_pass',
            research_decision: 'near_miss',
            short_trade_decision: 'selected',
            delta_summary: ['short trade target promoted a setup that research pipeline kept as near-miss'],
          },
        ],
      },
      feedback_summary: null,
      btst_control_tower_overview: {
        available: true,
        generated_at: '2026-03-31T08:19:55',
        comparison_basis: 'nightly_history',
        overall_delta_verdict: 'changed',
        operator_focus: ['replay cohort 变化: report_count +1, short_trade_only +1。'],
        current_reference: {
          report_dir: 'data/reports/paper_trading_window_recent',
          report_name: 'paper_trading_window_recent',
          selection_target: 'short_trade_only',
          trade_date: '2026-03-23',
          next_trade_date: '2026-03-24',
        },
        previous_reference: {
          report_dir: 'data/reports/paper_trading_window_prev',
          report_name: 'paper_trading_window_prev',
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
              report_name: 'paper_trading_window_recent',
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
              report_name: 'paper_trading_window_recent',
              trade_date: '2026-03-23',
              symbol: '300724',
              selection_target: 'short_trade_only',
            },
          },
        ],
        artifacts: {
          open_ready_delta_json: '/tmp/replay/btst_open_ready_delta_latest.json',
          nightly_control_tower_json: '/tmp/replay/btst_nightly_control_tower_latest.json',
          report_manifest_json: '/tmp/replay/report_manifest_latest.json',
        },
      },
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
    selection_artifact_overview: {
      available: false,
      trade_date_count: 0,
      available_trade_dates: [],
      write_status_counts: {},
      blocker_counts: [],
      short_trade_profile_overview: null,
      dual_target_overview: null,
      feedback_summary: null,
      btst_followup_overview: null,
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
    trade_date_target_index: [
      {
        trade_date: '2026-03-23',
        target_mode: 'dual_target',
        delta_classification_counts: { research_reject_short_pass: 1 },
        research_selected_count: 1,
        research_near_miss_count: 1,
        short_trade_selected_count: 1,
        short_trade_blocked_count: 1,
      },
    ],
    write_status_counts: { success: 1 },
    blocker_counts: [],
    short_trade_profile_overview: {
      profile_name_counts: { default: 1 },
      latest_profile_name: 'default',
      latest_profile_trade_date: '2026-03-23',
      latest_profile_config: { select_threshold: 0.58 },
    },
    dual_target_overview: {
      target_mode_counts: { dual_target: 1 },
      dual_target_trade_date_count: 1,
      selection_target_count: 2,
      research_target_count: 2,
      short_trade_target_count: 2,
      research_selected_count: 1,
      research_near_miss_count: 1,
      research_rejected_count: 0,
      short_trade_selected_count: 1,
      short_trade_near_miss_count: 0,
      short_trade_blocked_count: 1,
      short_trade_rejected_count: 0,
      shell_target_count: 0,
      delta_classification_counts: { research_reject_short_pass: 1 },
      dominant_delta_reasons: ['short trade target promoted a setup that research pipeline kept as near-miss'],
      dominant_delta_reason_counts: { 'short trade target promoted a setup that research pipeline kept as near-miss': 1 },
      representative_cases: [
        {
          trade_date: '2026-03-23',
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
      excluded_research_tickers: ['002001'],
      selected_count: 1,
      watchlist_count: 1,
      excluded_research_count: 1,
      artifacts: {},
    },
    btst_control_tower_overview: {
      available: true,
      generated_at: '2026-03-31T08:19:55',
      comparison_basis: 'nightly_history',
      overall_delta_verdict: 'changed',
      operator_focus: ['replay cohort 变化: report_count +1, short_trade_only +1。'],
      current_reference: {
        report_dir: 'data/reports/paper_trading_window_recent',
        report_name: 'paper_trading_window_recent',
        selection_target: 'short_trade_only',
        trade_date: '2026-03-23',
        next_trade_date: '2026-03-24',
      },
      previous_reference: {
        report_dir: 'data/reports/paper_trading_window_prev',
        report_name: 'paper_trading_window_prev',
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
            report_name: 'paper_trading_window_recent',
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
            report_name: 'paper_trading_window_recent',
            trade_date: '2026-03-23',
            symbol: '300724',
            selection_target: 'short_trade_only',
          },
        },
      ],
      artifacts: {
        open_ready_delta_json: '/tmp/replay/btst_open_ready_delta_latest.json',
        nightly_control_tower_json: '/tmp/replay/btst_nightly_control_tower_latest.json',
        report_manifest_json: '/tmp/replay/report_manifest_latest.json',
      },
    },
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
    getFeedbackActivityMock.mockResolvedValue({
      report_name: 'paper_trading_window_recent',
      reviewer: null,
      limit: 8,
      record_count: 0,
      recent_records: [],
      review_status_counts: {},
      tag_counts: {},
      reviewer_counts: {},
      report_counts: {},
    });
    getWorkflowQueueMock.mockResolvedValue({
      assignee: 'einstein',
      workflow_status: null,
      report_name: null,
      limit: 12,
      item_count: 1,
      items: [
        {
          report_name: 'paper_trading_window_recent',
          trade_date: '2026-03-23',
          symbol: '300724',
          review_scope: 'watchlist',
          feedback_path: '/tmp/replay/selection_artifacts/2026-03-23/research_feedback.jsonl',
          latest_feedback_created_at: '2026-03-23T10:00:00+08:00',
          latest_reviewer: 'einstein',
          latest_review_status: 'draft',
          latest_primary_tag: 'high_quality_selection',
          latest_tags: ['high_quality_selection'],
          latest_research_verdict: 'selected_for_good_reason',
          latest_notes: 'needs owner',
          assignee: null,
          workflow_status: 'unassigned',
        },
      ],
      workflow_status_counts: { unassigned: 1 },
      assignee_counts: { __unassigned__: 1 },
      report_counts: { paper_trading_window_recent: 1 },
    });

    render(<ReplayArtifactsSettings mode="workspace" />);

    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith('paper_trading_window_recent');
    });

    await waitFor(() => {
      expect(getSelectionArtifactDayMock).toHaveBeenCalledWith('paper_trading_window_recent', '2026-03-23');
    });

    await waitFor(() => {
      expect(getFeedbackActivityMock).toHaveBeenCalledWith({ reportName: 'paper_trading_window_recent', limit: 8 });
    });
    await waitFor(() => {
      expect(getWorkflowQueueMock).toHaveBeenCalledWith({ assignee: 'einstein', workflowStatus: undefined, limit: 12 });
    });

    expect(screen.getAllByText('paper_trading_window_recent').length).toBeGreaterThan(0);
    expect(screen.getByText('1 trade dates')).toBeInTheDocument();
    expect(screen.getAllByText('BTST Follow-Up').length).toBeGreaterThan(0);
    expect(screen.getAllByText('BTST 控制塔').length).toBeGreaterThan(0);
    expect(screen.getAllByText('有变化').length).toBeGreaterThan(0);
    expect(screen.getByText('已对齐最新 BTST | 有变化 | 回放')).toBeInTheDocument();
    expect(screen.getAllByText('已关闭路线').length).toBeGreaterThan(0);
    expect(screen.getAllByText('广义 stale/extension 惩罚放松').length).toBeGreaterThan(0);
    expect(screen.getAllByText('当前窗口已关闭').length).toBeGreaterThan(0);
    expect(screen.getAllByText('执行车道').length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: '打开当前 BTST 运行' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: '打开回放 300724' }).length).toBeGreaterThan(0);
    expect(screen.getAllByText('300757').length).toBeGreaterThan(0);
  });

  it('opens replay context from BTST rollout lane cards', async () => {
    const user = userEvent.setup();
    const focusableDayDetail: ReplaySelectionArtifactDay = {
      ...dayDetail,
      snapshot: {
        ...dayDetail.snapshot,
        selected: [
          {
            symbol: '300724',
            name: '捷佳伟创',
            decision: 'watchlist',
            score_b: 0.71,
            score_c: 0.63,
            score_final: 0.68,
            rank_in_watchlist: 1,
          },
        ],
      },
    };

    listMock.mockResolvedValue(reports);
    getMock.mockResolvedValue(detail);
    getSelectionArtifactDayMock.mockResolvedValue(focusableDayDetail);
    getFeedbackActivityMock.mockResolvedValue({
      report_name: 'paper_trading_window_recent',
      reviewer: null,
      limit: 8,
      record_count: 0,
      recent_records: [],
      review_status_counts: {},
      tag_counts: {},
      reviewer_counts: {},
      report_counts: {},
    });
    getWorkflowQueueMock.mockResolvedValue({
      assignee: 'einstein',
      workflow_status: null,
      report_name: null,
      limit: 12,
      item_count: 0,
      items: [],
      workflow_status_counts: {},
      assignee_counts: {},
      report_counts: {},
    });

    render(<ReplayArtifactsSettings mode="workspace" />);

    await screen.findAllByText('执行车道');
    await user.click(screen.getAllByRole('button', { name: '打开回放 300724' })[0]);

    await waitFor(() => {
      expect(screen.getByText('focus 300724')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByDisplayValue('300724')).toBeInTheDocument();
    });
  });

  it('renders dual-target snapshot sections and candidate target decisions', async () => {
    const dualTargetDetail: ReplaySelectionArtifactDay = {
      ...dayDetail,
      snapshot: {
        ...dayDetail.snapshot,
        target_mode: 'dual_target',
        target_summary: {
          target_mode: 'dual_target',
          selection_target_count: 2,
          research_target_count: 2,
          short_trade_target_count: 2,
          research_selected_count: 1,
          research_near_miss_count: 1,
          research_rejected_count: 0,
          short_trade_selected_count: 1,
          short_trade_near_miss_count: 0,
          short_trade_blocked_count: 1,
          short_trade_rejected_count: 0,
          shell_target_count: 0,
          delta_classification_counts: { research_reject_short_pass: 1 },
        },
        research_view: {
          selected_symbols: ['300724'],
          near_miss_symbols: ['002916'],
          rejected_symbols: [],
          blocker_counts: { analyst_divergence_high: 1 },
        },
        short_trade_view: {
          selected_symbols: ['002916'],
          near_miss_symbols: [],
          rejected_symbols: [],
          blocked_symbols: ['300724'],
          blocker_counts: { missing_trend_signal: 1 },
        },
        dual_target_delta: {
          delta_counts: { research_reject_short_pass: 1 },
          representative_cases: [
            {
              ticker: '002916',
              delta_classification: 'research_reject_short_pass',
              research_decision: 'near_miss',
              short_trade_decision: 'selected',
              delta_summary: ['short trade target promoted a setup that research pipeline kept as near-miss'],
            },
          ],
          dominant_delta_reasons: ['short trade target promoted a setup that research pipeline kept as near-miss'],
        },
        selected: [
          {
            symbol: '300724',
            name: '捷佳伟创',
            decision: 'watchlist',
            score_b: 0.71,
            score_c: 0.63,
            score_final: 0.68,
            rank_in_watchlist: 1,
            layer_b_summary: {
              top_factors: [{ name: 'fast_score', value: 0.71 }],
            },
            execution_bridge: {
              included_in_buy_orders: false,
              block_reason: 'blocked_by_reentry_score_confirmation',
            },
            target_decisions: {
              research: {
                target_type: 'research',
                decision: 'selected',
                score_target: 0.68,
                confidence: 0.68,
                expected_holding_window: 'swing_research_window',
                preferred_entry_mode: 'watchlist_pullback',
                metrics_payload: {
                  score_b: 0.71,
                  score_c: 0.63,
                  score_final: 0.68,
                  quality_score: 0.66,
                },
                explainability_payload: {
                  source: 'research_target_rules_v1',
                },
              },
              short_trade: {
                target_type: 'short_trade',
                decision: 'blocked',
                score_target: 0.31,
                confidence: 0.44,
                blockers: ['missing_trend_signal'],
                expected_holding_window: 't1_short_trade',
                preferred_entry_mode: 'next_day_breakout_confirmation',
                top_reasons: ['breakout_freshness=0.41'],
                metrics_payload: {
                  breakout_freshness: 0.41,
                  trend_acceleration: 0.29,
                  volume_expansion_quality: 0.32,
                  catalyst_freshness: 0.21,
                },
                explainability_payload: {
                  source: 'watchlist_filter_diagnostics',
                  target_profile: 'default',
                },
              },
            },
          },
        ],
        rejected: [
          {
            symbol: '002916',
            name: '深南电路',
            rejection_stage: 'watchlist',
            score_b: 0.65,
            score_c: 0.44,
            score_final: 0.49,
            rejection_reason_codes: ['analyst_divergence_high'],
            rejection_reason_text: 'divergence high',
            target_decisions: {
              research: {
                target_type: 'research',
                decision: 'near_miss',
                score_target: 0.49,
                confidence: 0.61,
                top_reasons: ['score_target close to watchlist threshold'],
              },
              short_trade: {
                target_type: 'short_trade',
                decision: 'selected',
                score_target: 0.62,
                confidence: 0.66,
                expected_holding_window: 't1_short_trade',
                preferred_entry_mode: 'next_day_breakout_confirmation',
                top_reasons: ['trend_acceleration=0.66', 'catalyst_freshness=0.59'],
                metrics_payload: {
                  breakout_freshness: 0.64,
                  trend_acceleration: 0.66,
                  volume_expansion_quality: 0.58,
                  catalyst_freshness: 0.59,
                },
                explainability_payload: {
                  source: 'watchlist_filter_diagnostics',
                  target_profile: 'aggressive',
                },
              },
            },
          },
        ],
      },
    };

    listMock.mockResolvedValue(reports);
    getMock.mockResolvedValue(detail);
    getSelectionArtifactDayMock.mockResolvedValue(dualTargetDetail);
    getFeedbackActivityMock.mockResolvedValue({
      report_name: 'paper_trading_window_recent',
      reviewer: null,
      limit: 8,
      record_count: 0,
      recent_records: [],
      review_status_counts: {},
      tag_counts: {},
      reviewer_counts: {},
      report_counts: {},
    });
    getWorkflowQueueMock.mockResolvedValue({
      assignee: 'einstein',
      workflow_status: null,
      report_name: null,
      limit: 12,
      item_count: 2,
      items: [
        {
          report_name: 'paper_trading_window_recent',
          trade_date: '2026-03-23',
          symbol: '002916',
          review_scope: 'near_miss',
          feedback_path: '/tmp/replay/selection_artifacts/2026-03-23/research_feedback.jsonl',
          latest_feedback_created_at: '2026-03-23T11:00:00+08:00',
          latest_reviewer: 'einstein',
          latest_review_status: 'draft',
          latest_primary_tag: 'high_quality_selection',
          latest_tags: ['high_quality_selection'],
          latest_research_verdict: 'needs_more_confirmation',
          latest_notes: 'focus item',
          assignee: null,
          workflow_status: 'unassigned',
        },
        {
          report_name: 'paper_trading_window_high_dual_target',
          trade_date: '2026-03-08',
          symbol: '300724',
          review_scope: 'watchlist',
          feedback_path: '/tmp/replay/high/selection_artifacts/2026-03-08/research_feedback.jsonl',
          latest_feedback_created_at: '2026-03-23T11:00:00+08:00',
          latest_reviewer: 'curie',
          latest_review_status: 'assigned',
          latest_primary_tag: 'threshold_false_negative',
          latest_tags: ['threshold_false_negative'],
          latest_research_verdict: 'needs_more_confirmation',
          latest_notes: 'other item',
          assignee: 'curie',
          workflow_status: 'assigned',
        },
      ],
      workflow_status_counts: { unassigned: 1, assigned: 1 },
      assignee_counts: { __unassigned__: 1, curie: 1 },
      report_counts: { paper_trading_window_recent: 1, paper_trading_window_high_dual_target: 1 },
    });

    render(<ReplayArtifactsSettings mode="workspace" />);

    await screen.findByText('Dual Target Snapshot');
    expect(screen.getByText('selected 1 | near 1')).toBeInTheDocument();
    expect(screen.getByText('blocked 1 | rejected 0')).toBeInTheDocument();
    expect(screen.getByText('selected: 300724')).toBeInTheDocument();
    expect(screen.getByText('blocked: 300724')).toBeInTheDocument();
    expect(screen.getAllByText(/002916 \| research_reject_short_pass \| research near_miss \| short selected/).length).toBeGreaterThan(0);
    expect(screen.getByText('selected | score 0.680')).toBeInTheDocument();
    expect(screen.getByText('blocked | score 0.310 | blockers missing_trend_signal')).toBeInTheDocument();
    expect(screen.getByText('near_miss | score 0.490')).toBeInTheDocument();
    expect(screen.getByText('selected | score 0.620')).toBeInTheDocument();
    expect(screen.getByText('Target Explainability')).toBeInTheDocument();
    expect(screen.getByText('profile default | source watchlist_filter_diagnostics')).toBeInTheDocument();
    expect(screen.getAllByText('holding t1_short_trade | entry next_day_breakout_confirmation').length).toBeGreaterThan(0);
    expect(screen.getByText('metrics breakout_freshness:0.410 | trend_acceleration:0.290 | volume_expansion_quality:0.320 | catalyst_freshness:0.210')).toBeInTheDocument();
    expect(screen.getByText('profile aggressive | source watchlist_filter_diagnostics')).toBeInTheDocument();
  });

  it('filters report rail by dual-target metadata and jumps from representative case to focused symbol', async () => {
    const user = userEvent.setup();
    const profileFilterReports: ReplayArtifactSummary[] = [
      reports[0],
      {
        ...reports[1],
        report_dir: 'paper_trading_window_conservative',
        selection_artifact_overview: {
          available: true,
          artifact_root: '/tmp/replay/conservative/selection_artifacts',
          trade_date_count: 2,
          available_trade_dates: ['2026-03-10', '2026-03-11'],
          trade_date_target_index: [
            {
              trade_date: '2026-03-10',
              target_mode: 'dual_target',
              short_trade_profile_name: 'conservative',
              delta_classification_counts: { research_reject_short_pass: 1 },
              research_selected_count: 1,
              research_near_miss_count: 0,
              short_trade_selected_count: 1,
              short_trade_blocked_count: 0,
            },
            {
              trade_date: '2026-03-11',
              target_mode: 'dual_target',
              short_trade_profile_name: 'conservative',
              delta_classification_counts: { research_reject_short_pass: 1 },
              research_selected_count: 1,
              research_near_miss_count: 0,
              short_trade_selected_count: 1,
              short_trade_blocked_count: 1,
            },
          ],
          write_status_counts: { success: 2 },
          blocker_counts: [],
          short_trade_profile_overview: {
            profile_name_counts: { conservative: 2 },
            latest_profile_name: 'conservative',
            latest_profile_trade_date: '2026-03-11',
            latest_profile_config: { select_threshold: 0.62 },
          },
          dual_target_overview: {
            target_mode_counts: { dual_target: 2 },
            dual_target_trade_date_count: 2,
            selection_target_count: 4,
            research_target_count: 4,
            short_trade_target_count: 4,
            research_selected_count: 2,
            research_near_miss_count: 0,
            research_rejected_count: 0,
            short_trade_selected_count: 2,
            short_trade_near_miss_count: 0,
            short_trade_blocked_count: 1,
            short_trade_rejected_count: 0,
            shell_target_count: 0,
            delta_classification_counts: { research_reject_short_pass: 2 },
            dominant_delta_reasons: ['conservative short profile window'],
            dominant_delta_reason_counts: { 'conservative short profile window': 2 },
            representative_cases: [],
          },
          feedback_summary: null,
        },
      },
    ];
    const dualTargetDetail: ReplaySelectionArtifactDay = {
      ...dayDetail,
      snapshot: {
        ...dayDetail.snapshot,
        target_mode: 'dual_target',
        target_summary: {
          target_mode: 'dual_target',
          selection_target_count: 2,
          research_target_count: 2,
          short_trade_target_count: 2,
          research_selected_count: 1,
          research_near_miss_count: 1,
          research_rejected_count: 0,
          short_trade_selected_count: 1,
          short_trade_near_miss_count: 0,
          short_trade_blocked_count: 1,
          short_trade_rejected_count: 0,
          shell_target_count: 0,
          delta_classification_counts: { research_reject_short_pass: 1 },
        },
        research_view: {
          selected_symbols: ['300724'],
          near_miss_symbols: ['002916'],
          rejected_symbols: [],
          blocker_counts: { analyst_divergence_high: 1 },
        },
        short_trade_view: {
          selected_symbols: ['002916'],
          near_miss_symbols: [],
          rejected_symbols: [],
          blocked_symbols: ['300724'],
          blocker_counts: { missing_trend_signal: 1 },
        },
        dual_target_delta: {
          delta_counts: { research_reject_short_pass: 1 },
          representative_cases: [
            {
              ticker: '002916',
              delta_classification: 'research_reject_short_pass',
              research_decision: 'near_miss',
              short_trade_decision: 'selected',
              delta_summary: ['short trade target promoted a setup that research pipeline kept as near-miss'],
            },
          ],
          dominant_delta_reasons: ['short trade target promoted a setup that research pipeline kept as near-miss'],
        },
        selected: [
          {
            symbol: '300724',
            name: '捷佳伟创',
            decision: 'watchlist',
            score_b: 0.71,
            score_c: 0.63,
            score_final: 0.68,
            rank_in_watchlist: 1,
            target_decisions: {
              research: {
                target_type: 'research',
                decision: 'selected',
                score_target: 0.68,
                confidence: 0.68,
              },
            },
          },
        ],
        rejected: [
          {
            symbol: '002916',
            name: '深南电路',
            rejection_stage: 'watchlist',
            score_b: 0.65,
            score_c: 0.44,
            score_final: 0.49,
            rejection_reason_codes: ['analyst_divergence_high'],
            rejection_reason_text: 'divergence high',
            target_decisions: {
              research: {
                target_type: 'research',
                decision: 'near_miss',
                score_target: 0.49,
                confidence: 0.61,
              },
              short_trade: {
                target_type: 'short_trade',
                decision: 'selected',
                score_target: 0.62,
                confidence: 0.66,
              },
            },
          },
        ],
      },
    };

    listMock.mockResolvedValue(profileFilterReports);
    getMock.mockResolvedValue(detail);
    getSelectionArtifactDayMock.mockResolvedValue(dualTargetDetail);
    getFeedbackActivityMock.mockResolvedValue({
      report_name: 'paper_trading_window_recent',
      reviewer: null,
      limit: 8,
      record_count: 0,
      recent_records: [],
      review_status_counts: {},
      tag_counts: {},
      reviewer_counts: {},
      report_counts: {},
    });
    getWorkflowQueueMock.mockResolvedValue({
      assignee: 'einstein',
      workflow_status: null,
      report_name: null,
      limit: 12,
      item_count: 0,
      items: [],
      workflow_status_counts: {},
      assignee_counts: {},
      report_counts: {},
    });

    render(<ReplayArtifactsSettings mode="workspace" />);

    await screen.findByText('Report-Level Dual Target Overview');

  await user.selectOptions(screen.getByLabelText('Report Short Profile Filter'), 'default');

  expect(screen.queryByText('paper_trading_window_conservative')).not.toBeInTheDocument();
  expect(screen.getAllByText('paper_trading_window_recent').length).toBeGreaterThan(0);

    await user.selectOptions(screen.getByLabelText('Report Target Mode Filter'), 'dual_target');
    await user.selectOptions(screen.getByLabelText('Report Delta Filter'), 'research_reject_short_pass');

  expect(screen.queryByText('paper_trading_window_conservative')).not.toBeInTheDocument();
    expect(screen.getAllByText('paper_trading_window_recent').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: /2026-03-23 002916 \| research_reject_short_pass \| research near_miss \| short selected/i }));

    expect(await screen.findByText('focus 002916')).toBeInTheDocument();
    expect(screen.getByDisplayValue('002916')).toBeInTheDocument();
    expect(screen.getByText('No selected candidates match the current focus.')).toBeInTheDocument();
    expect(screen.getAllByText('002916').length).toBeGreaterThan(0);
  });

  it('filters trade dates by dual-target metadata, syncs focus into feedback, and sorts report rail', async () => {
    const user = userEvent.setup();
    const sortableReports: ReplayArtifactSummary[] = [
      {
        ...reports[0],
        report_dir: 'paper_trading_window_recent',
        selection_artifact_overview: {
          ...reports[0].selection_artifact_overview,
          trade_date_count: 2,
          available_trade_dates: ['2026-03-22', '2026-03-23'],
          trade_date_target_index: [
            {
              trade_date: '2026-03-22',
              target_mode: 'research_only',
              short_trade_profile_name: 'default',
              delta_classification_counts: {},
              research_selected_count: 1,
              research_near_miss_count: 0,
              short_trade_selected_count: 0,
              short_trade_blocked_count: 0,
            },
            {
              trade_date: '2026-03-23',
              target_mode: 'dual_target',
              short_trade_profile_name: 'aggressive',
              delta_classification_counts: { research_reject_short_pass: 1 },
              research_selected_count: 1,
              research_near_miss_count: 1,
              short_trade_selected_count: 1,
              short_trade_blocked_count: 1,
            },
          ],
          dual_target_overview: {
            ...(reports[0].selection_artifact_overview.dual_target_overview as NonNullable<ReplayArtifactSummary['selection_artifact_overview']['dual_target_overview']>),
            dual_target_trade_date_count: 1,
            delta_classification_counts: { research_reject_short_pass: 1 },
          },
          short_trade_profile_overview: {
            profile_name_counts: { default: 1, aggressive: 1 },
            latest_profile_name: 'aggressive',
            latest_profile_trade_date: '2026-03-23',
            latest_profile_config: { select_threshold: 0.54 },
          },
        },
      },
      {
        ...reports[1],
        report_dir: 'paper_trading_window_high_dual_target',
        window: { start_date: '2026-03-01', end_date: '2026-03-08' },
        selection_artifact_overview: {
          available: true,
          artifact_root: '/tmp/replay/high/selection_artifacts',
          trade_date_count: 3,
          available_trade_dates: ['2026-03-06', '2026-03-07', '2026-03-08'],
          trade_date_target_index: [
            {
              trade_date: '2026-03-06',
              target_mode: 'dual_target',
              short_trade_profile_name: 'conservative',
              delta_classification_counts: { research_reject_short_pass: 2 },
              research_selected_count: 1,
              research_near_miss_count: 1,
              short_trade_selected_count: 1,
              short_trade_blocked_count: 0,
            },
            {
              trade_date: '2026-03-07',
              target_mode: 'dual_target',
              short_trade_profile_name: 'conservative',
              delta_classification_counts: { research_reject_short_pass: 1 },
              research_selected_count: 1,
              research_near_miss_count: 0,
              short_trade_selected_count: 1,
              short_trade_blocked_count: 1,
            },
            {
              trade_date: '2026-03-08',
              target_mode: 'dual_target',
              short_trade_profile_name: 'conservative',
              delta_classification_counts: { research_reject_short_pass: 1 },
              research_selected_count: 1,
              research_near_miss_count: 0,
              short_trade_selected_count: 1,
              short_trade_blocked_count: 0,
            },
          ],
          write_status_counts: { success: 3 },
          blocker_counts: [],
          dual_target_overview: {
            target_mode_counts: { dual_target: 3 },
            dual_target_trade_date_count: 3,
            selection_target_count: 6,
            research_target_count: 6,
            short_trade_target_count: 6,
            research_selected_count: 3,
            research_near_miss_count: 1,
            research_rejected_count: 0,
            short_trade_selected_count: 3,
            short_trade_near_miss_count: 0,
            short_trade_blocked_count: 1,
            short_trade_rejected_count: 0,
            shell_target_count: 0,
            delta_classification_counts: { research_reject_short_pass: 4 },
            dominant_delta_reasons: ['higher dual target density'],
            dominant_delta_reason_counts: { 'higher dual target density': 2 },
            representative_cases: [],
          },
          short_trade_profile_overview: {
            profile_name_counts: { conservative: 3 },
            latest_profile_name: 'conservative',
            latest_profile_trade_date: '2026-03-08',
            latest_profile_config: { select_threshold: 0.62 },
          },
          feedback_summary: null,
        },
      },
    ];

    const detailWithTradeDateIndex: ReplayArtifactDetail = {
      ...detail,
      selection_artifact_overview: {
        ...detail.selection_artifact_overview,
        trade_date_count: 2,
        available_trade_dates: ['2026-03-22', '2026-03-23'],
        trade_date_target_index: [
          {
            trade_date: '2026-03-22',
            target_mode: 'research_only',
            short_trade_profile_name: 'default',
            delta_classification_counts: {},
            research_selected_count: 1,
            research_near_miss_count: 0,
            short_trade_selected_count: 0,
            short_trade_blocked_count: 0,
          },
          {
            trade_date: '2026-03-23',
            target_mode: 'dual_target',
            short_trade_profile_name: 'aggressive',
            delta_classification_counts: { research_reject_short_pass: 1 },
            research_selected_count: 1,
            research_near_miss_count: 1,
            short_trade_selected_count: 1,
            short_trade_blocked_count: 1,
          },
        ],
      },
    };

    const researchOnlyDayDetail: ReplaySelectionArtifactDay = {
      ...dayDetail,
      trade_date: '2026-03-22',
      snapshot: {
        ...dayDetail.snapshot,
        trade_date: '2026-03-22',
        target_mode: 'research_only',
        selected: [
          {
            symbol: '300724',
            name: '捷佳伟创',
            decision: 'watchlist',
            score_b: 0.71,
            score_c: 0.63,
            score_final: 0.68,
            rank_in_watchlist: 1,
          },
        ],
        rejected: [],
      },
      feedback_options: {
        allowed_tags: ['high_quality_selection', 'thesis_clear'],
        allowed_review_statuses: ['draft', 'final'],
      },
    };

    const dualTargetDayDetail: ReplaySelectionArtifactDay = {
      ...dayDetail,
      feedback_options: {
        allowed_tags: ['high_quality_selection', 'thesis_clear'],
        allowed_review_statuses: ['draft', 'final'],
      },
      snapshot: {
        ...dayDetail.snapshot,
        target_mode: 'dual_target',
        trade_date: '2026-03-23',
        pipeline_config_snapshot: {
          short_trade_target_profile: {
            name: 'aggressive',
            config: {
              select_threshold: 0.54,
            },
          },
        },
        selected: [
          {
            symbol: '300724',
            name: '捷佳伟创',
            decision: 'watchlist',
            score_b: 0.71,
            score_c: 0.63,
            score_final: 0.68,
            rank_in_watchlist: 1,
            research_prompts: {
              why_selected: ['fast score high'],
              what_to_check: ['confirmation strength'],
            },
            target_decisions: {
              research: {
                target_type: 'research',
                decision: 'selected',
                score_target: 0.68,
                confidence: 0.68,
                explainability_payload: {
                  source: 'watchlist',
                },
              },
            },
          },
        ],
        rejected: [
          {
            symbol: '002916',
            name: '深南电路',
            rejection_stage: 'watchlist',
            score_b: 0.65,
            score_c: 0.44,
            score_final: 0.49,
            rejection_reason_codes: ['analyst_divergence_high'],
            rejection_reason_text: 'divergence high',
            target_decisions: {
              research: {
                target_type: 'research',
                decision: 'near_miss',
                score_target: 0.49,
                confidence: 0.61,
              },
              short_trade: {
                target_type: 'short_trade',
                decision: 'selected',
                score_target: 0.62,
                confidence: 0.66,
                explainability_payload: {
                  target_profile: 'aggressive',
                  source: 'layer_b_boundary',
                },
              },
            },
          },
        ],
      },
    };

    listMock.mockResolvedValue(sortableReports);
    getMock.mockResolvedValue(detailWithTradeDateIndex);
    getSelectionArtifactDayMock.mockImplementation(async (_reportDir: string, tradeDate: string) => (tradeDate === '2026-03-22' ? researchOnlyDayDetail : dualTargetDayDetail));
    getFeedbackActivityMock.mockResolvedValue({
      report_name: 'paper_trading_window_recent',
      reviewer: null,
      limit: 8,
      record_count: 0,
      recent_records: [],
      review_status_counts: {},
      tag_counts: {},
      reviewer_counts: {},
      report_counts: {},
    });
    getWorkflowQueueMock.mockResolvedValue({
      assignee: 'einstein',
      workflow_status: null,
      report_name: null,
      limit: 12,
      item_count: 0,
      items: [],
      workflow_status_counts: {},
      assignee_counts: {},
      report_counts: {},
    });
    appendSelectionFeedbackMock.mockResolvedValue({
      record: {
        feedback_version: 'v1',
        artifact_version: 'v1',
        label_version: 'v1',
        run_id: 'run-1',
        trade_date: '2026-03-23',
        symbol: '002916',
        review_scope: 'watchlist',
        reviewer: 'einstein',
        review_status: 'draft',
        primary_tag: 'high_quality_selection',
        tags: [],
        confidence: 0.77,
        research_verdict: 'needs_more_confirmation',
        notes: 'focused symbol feedback',
        created_at: '2026-03-23T11:00:00+08:00',
      },
      feedback_record_count: 1,
      feedback_summary: {
        label_version: 'v1',
        feedback_count: 1,
        final_feedback_count: 0,
        symbols: ['002916'],
        reviewers: ['einstein'],
        primary_tag_counts: { high_quality_selection: 1 },
        tag_counts: { high_quality_selection: 1 },
        review_status_counts: { draft: 1 },
        verdict_counts: { needs_more_confirmation: 1 },
        latest_created_at: '2026-03-23T11:00:00+08:00',
      },
      directory_summary: {},
    });

    render(<ReplayArtifactsSettings mode="workspace" />);

    await screen.findByText('Report-Level Dual Target Overview');
    await user.click(screen.getByRole('button', { name: /2026-03-22 research_only/i }));

    await waitFor(() => {
      expect(getSelectionArtifactDayMock).toHaveBeenLastCalledWith('paper_trading_window_recent', '2026-03-22');
    });

    await user.selectOptions(screen.getByLabelText('Report Sort'), 'dual_target_days_desc');

    const highDualTargetButton = screen.getByRole('button', { name: /paper_trading_window_high_dual_target/i });
    const recentButton = screen.getByRole('button', { name: /paper_trading_window_recent/i });
    expect(highDualTargetButton.compareDocumentPosition(recentButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    await user.selectOptions(screen.getByLabelText('Trade Date Short Profile Filter'), 'aggressive');

    await waitFor(() => {
      expect(getSelectionArtifactDayMock).toHaveBeenLastCalledWith('paper_trading_window_recent', '2026-03-23');
    });
    expect(screen.getAllByText('1 / 2 trade dates').length).toBeGreaterThan(0);
    expect(screen.getAllByText('profile aggressive').length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /2026-03-22 research_only/i })).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Trade Date Short Profile Filter'), 'all');

    await user.selectOptions(screen.getByLabelText('Trade Date Target Mode Filter'), 'research_only');

    await waitFor(() => {
      expect(getSelectionArtifactDayMock).toHaveBeenLastCalledWith('paper_trading_window_recent', '2026-03-22');
    });
    expect(screen.getByDisplayValue('2026-03-22')).toBeInTheDocument();
    expect(screen.getAllByText('1 / 2 trade dates').length).toBeGreaterThan(0);

    await user.selectOptions(screen.getByLabelText('Trade Date Target Mode Filter'), 'dual_target');

    await waitFor(() => {
      expect(getSelectionArtifactDayMock).toHaveBeenLastCalledWith('paper_trading_window_recent', '2026-03-23');
    });

    expect(screen.getAllByText(/short profile/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/default:1 \| aggressive:1 \| latest aggressive/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText('profile aggressive').length).toBeGreaterThan(0);

    expect(screen.getByText('Short Trade Profile')).toBeInTheDocument();
    expect(screen.getAllByText('aggressive').length).toBeGreaterThan(0);

    await user.selectOptions(screen.getByLabelText('Explainability Profile Filter'), 'aggressive');
    await user.selectOptions(screen.getByLabelText('Explainability Source Filter'), 'layer_b_boundary');
    await user.selectOptions(screen.getByLabelText('Explainability Decision Filter'), 'selected');

    expect(screen.getAllByText('profile aggressive').length).toBeGreaterThan(0);
    expect(screen.getByText('source layer_b_boundary')).toBeInTheDocument();
    expect(screen.getByText('decision selected')).toBeInTheDocument();
    expect(screen.getByText('No selected candidates match the current focus.')).toBeInTheDocument();
    expect(screen.getAllByText('002916').length).toBeGreaterThan(0);

    await user.selectOptions(screen.getByLabelText('Focus Symbol'), '002916');
    await user.click(screen.getByRole('button', { name: 'current report only' }));
    await user.click(screen.getByRole('button', { name: 'focus symbol only' }));
    await user.selectOptions(screen.getByLabelText('Primary Tag'), 'high_quality_selection');
    await user.clear(screen.getByLabelText('Research Verdict'));
    await user.type(screen.getByLabelText('Research Verdict'), 'needs_more_confirmation');
    await user.clear(screen.getByLabelText('Confidence'));
    await user.type(screen.getByLabelText('Confidence'), '0.77');
    await user.type(screen.getByLabelText('Notes'), 'focused symbol feedback');
    await user.click(screen.getByRole('button', { name: 'Append Feedback' }));

    await waitFor(() => {
      expect(appendSelectionFeedbackMock).toHaveBeenCalledWith('paper_trading_window_recent', '2026-03-23', expect.objectContaining({
        symbol: '002916',
        primary_tag: 'high_quality_selection',
      }));
    });
    expect(screen.getByText('Focus Queue')).toBeInTheDocument();
  });

  it('submits feedback, refreshes the artifact detail, and renders records in reverse chronological order', async () => {
    const user = userEvent.setup();
    const detailAfterAppend: ReplayArtifactDetail = {
      ...detail,
      selection_artifact_overview: {
        ...detail.selection_artifact_overview,
        feedback_summary: {
          overall: {
            feedback_count: 2,
            final_feedback_count: 1,
          },
          feedback_file_count: 1,
          trade_date_count: 1,
        },
      },
    };
    const initialDayDetail: ReplaySelectionArtifactDay = {
      ...dayDetail,
      snapshot: {
        ...dayDetail.snapshot,
        selected: [
          {
            symbol: '300724',
            name: '捷佳伟创',
            decision: 'watchlist',
            score_b: 0.71,
            score_c: 0.63,
            score_final: 0.68,
            rank_in_watchlist: 1,
            layer_b_summary: {
              top_factors: [{ name: 'fast_score', value: 0.71 }],
            },
            research_prompts: {
              why_selected: ['fast score high'],
              what_to_check: ['confirmation strength'],
            },
          },
        ],
      },
      feedback_options: {
        allowed_tags: ['high_quality_selection', 'thesis_clear'],
        allowed_review_statuses: ['draft', 'final'],
      },
    };
    const refreshedDayDetail: ReplaySelectionArtifactDay = {
      ...initialDayDetail,
      feedback_record_count: 2,
      feedback_records: [
        {
          feedback_version: 'v1',
          artifact_version: 'v1',
          label_version: 'v1',
          run_id: 'run-1',
          trade_date: '2026-03-23',
          symbol: '300724',
          review_scope: 'watchlist',
          reviewer: 'einstein',
          review_status: 'draft',
          primary_tag: 'thesis_clear',
          tags: ['thesis_clear'],
          confidence: 0.6,
          research_verdict: 'needs_more_confirmation',
          notes: 'older record',
          created_at: '2026-03-23T10:00:00+08:00',
        },
        {
          feedback_version: 'v1',
          artifact_version: 'v1',
          label_version: 'v1',
          run_id: 'run-1',
          trade_date: '2026-03-23',
          symbol: '300724',
          review_scope: 'watchlist',
          reviewer: 'einstein',
          review_status: 'final',
          primary_tag: 'high_quality_selection',
          tags: ['high_quality_selection', 'thesis_clear'],
          confidence: 0.91,
          research_verdict: 'selected_for_good_reason',
          notes: 'newer record',
          created_at: '2026-03-23T11:00:00+08:00',
        },
      ],
      feedback_summary: {
        label_version: 'v1',
        feedback_count: 2,
        final_feedback_count: 1,
        symbols: ['300724'],
        reviewers: ['einstein'],
        primary_tag_counts: {
          high_quality_selection: 1,
          thesis_clear: 1,
        },
        tag_counts: {
          high_quality_selection: 1,
          thesis_clear: 2,
        },
        review_status_counts: {
          draft: 1,
          final: 1,
        },
        verdict_counts: {
          needs_more_confirmation: 1,
          selected_for_good_reason: 1,
        },
        latest_created_at: '2026-03-23T11:00:00+08:00',
      },
    };

    listMock.mockResolvedValue(reports);
    getMock.mockResolvedValueOnce(detail).mockResolvedValueOnce(detailAfterAppend);
    getSelectionArtifactDayMock.mockResolvedValueOnce(initialDayDetail).mockResolvedValueOnce(refreshedDayDetail);
    getFeedbackActivityMock.mockResolvedValueOnce({
      report_name: 'paper_trading_window_recent',
      reviewer: null,
      limit: 8,
      record_count: 1,
      recent_records: [
        {
          report_name: 'paper_trading_window_recent',
          trade_date: '2026-03-23',
          symbol: '300724',
          review_scope: 'watchlist',
          reviewer: 'einstein',
          review_status: 'draft',
          primary_tag: 'thesis_clear',
          tags: ['thesis_clear'],
          confidence: 0.6,
          research_verdict: 'needs_more_confirmation',
          notes: 'older record',
          created_at: '2026-03-23T10:00:00+08:00',
          feedback_path: '/tmp/replay/selection_artifacts/2026-03-23/research_feedback.jsonl',
        },
      ],
      review_status_counts: { draft: 1 },
      tag_counts: { thesis_clear: 1 },
      reviewer_counts: { einstein: 1 },
      report_counts: { paper_trading_window_recent: 1 },
    }).mockResolvedValueOnce({
      report_name: 'paper_trading_window_recent',
      reviewer: null,
      limit: 8,
      record_count: 2,
      recent_records: [
        {
          report_name: 'paper_trading_window_recent',
          trade_date: '2026-03-23',
          symbol: '300724',
          review_scope: 'watchlist',
          reviewer: 'einstein',
          review_status: 'final',
          primary_tag: 'high_quality_selection',
          tags: ['high_quality_selection', 'thesis_clear'],
          confidence: 0.91,
          research_verdict: 'selected_for_good_reason',
          notes: 'newer record',
          created_at: '2026-03-23T11:00:00+08:00',
          feedback_path: '/tmp/replay/selection_artifacts/2026-03-23/research_feedback.jsonl',
        },
        {
          report_name: 'paper_trading_window_recent',
          trade_date: '2026-03-23',
          symbol: '300724',
          review_scope: 'watchlist',
          reviewer: 'einstein',
          review_status: 'draft',
          primary_tag: 'thesis_clear',
          tags: ['thesis_clear'],
          confidence: 0.6,
          research_verdict: 'needs_more_confirmation',
          notes: 'older record',
          created_at: '2026-03-23T10:00:00+08:00',
          feedback_path: '/tmp/replay/selection_artifacts/2026-03-23/research_feedback.jsonl',
        },
      ],
      review_status_counts: { draft: 1, final: 1 },
      tag_counts: { thesis_clear: 2, high_quality_selection: 1 },
      reviewer_counts: { einstein: 2 },
      report_counts: { paper_trading_window_recent: 2 },
    });
    getWorkflowQueueMock.mockResolvedValueOnce({
      assignee: 'einstein',
      workflow_status: null,
      report_name: null,
      limit: 12,
      item_count: 0,
      items: [],
      workflow_status_counts: {},
      assignee_counts: {},
      report_counts: {},
    }).mockResolvedValueOnce({
      assignee: 'einstein',
      workflow_status: null,
      report_name: null,
      limit: 12,
      item_count: 1,
      items: [
        {
          report_name: 'paper_trading_window_recent',
          trade_date: '2026-03-23',
          symbol: '300724',
          review_scope: 'watchlist',
          feedback_path: '/tmp/replay/selection_artifacts/2026-03-23/research_feedback.jsonl',
          latest_feedback_created_at: '2026-03-23T11:00:00+08:00',
          latest_reviewer: 'einstein',
          latest_review_status: 'draft',
          latest_primary_tag: 'high_quality_selection',
          latest_tags: ['high_quality_selection'],
          latest_research_verdict: 'selected_for_good_reason',
          latest_notes: 'newer record',
          assignee: null,
          workflow_status: 'unassigned',
        },
      ],
      workflow_status_counts: { unassigned: 1 },
      assignee_counts: { __unassigned__: 1 },
      report_counts: { paper_trading_window_recent: 1 },
    });
    appendSelectionFeedbackMock.mockResolvedValue({
      record: refreshedDayDetail.feedback_records[1],
      feedback_record_count: 2,
      feedback_summary: refreshedDayDetail.feedback_summary,
      directory_summary: {},
    });

    render(<ReplayArtifactsSettings mode="workspace" />);

    await waitFor(() => {
      expect(getSelectionArtifactDayMock).toHaveBeenCalledWith('paper_trading_window_recent', '2026-03-23');
    });
    await screen.findByText('Append Research Feedback');

    await user.selectOptions(screen.getByLabelText('Primary Tag'), 'high_quality_selection');
    await user.type(screen.getByLabelText('Additional Tags'), 'thesis_clear');
    await user.selectOptions(screen.getAllByLabelText('Review Status')[0], 'final');
    await user.clear(screen.getByLabelText('Research Verdict'));
    await user.type(screen.getByLabelText('Research Verdict'), 'selected_for_good_reason');
    await user.clear(screen.getByLabelText('Confidence'));
    await user.type(screen.getByLabelText('Confidence'), '0.91');
    await user.type(screen.getByLabelText('Notes'), 'newer record');
    await user.click(screen.getByRole('button', { name: 'Append Feedback' }));

    await waitFor(() => {
      expect(appendSelectionFeedbackMock).toHaveBeenCalledWith('paper_trading_window_recent', '2026-03-23', {
        symbol: '300724',
        primary_tag: 'high_quality_selection',
        research_verdict: 'selected_for_good_reason',
        tags: ['thesis_clear'],
        review_status: 'final',
        review_scope: 'watchlist',
        confidence: 0.91,
        notes: 'newer record',
      });
    });

    await waitFor(() => {
      expect(getMock).toHaveBeenCalledTimes(2);
      expect(getSelectionArtifactDayMock).toHaveBeenCalledTimes(2);
      expect(getFeedbackActivityMock).toHaveBeenCalledTimes(2);
      expect(getWorkflowQueueMock).toHaveBeenCalledTimes(2);
    });

    const feedbackTable = screen.getAllByRole('table').at(-1);
    expect(feedbackTable).toBeDefined();
    const createdAtCells = within(feedbackTable as HTMLElement).getAllByText(/2026-03-23T1[01]:00:00\+08:00/);
    expect(createdAtCells).toHaveLength(2);
    expect(createdAtCells[0].textContent).toBe('2026-03-23T11:00:00+08:00');
    expect(createdAtCells[1].textContent).toBe('2026-03-23T10:00:00+08:00');
    expect(screen.getByText('2 records')).toBeInTheDocument();
    expect(screen.getByText('2 recent records')).toBeInTheDocument();
  });

  it('submits batch feedback for multiple symbols and refreshes the activity panel', async () => {
    const user = userEvent.setup();
    const detailAfterBatchAppend: ReplayArtifactDetail = {
      ...detail,
      selection_artifact_overview: {
        ...detail.selection_artifact_overview,
        feedback_summary: {
          overall: {
            feedback_count: 2,
            final_feedback_count: 2,
          },
          feedback_file_count: 1,
          trade_date_count: 1,
        },
      },
    };
    const batchInitialDayDetail: ReplaySelectionArtifactDay = {
      ...dayDetail,
      snapshot: {
        ...dayDetail.snapshot,
        selected: [
          {
            symbol: '300724',
            name: '捷佳伟创',
            decision: 'watchlist',
            score_b: 0.71,
            score_c: 0.63,
            score_final: 0.68,
            rank_in_watchlist: 1,
          },
        ],
        rejected: [
          {
            symbol: '002916',
            name: '深南电路',
            rejection_stage: 'layer_c',
            score_b: 0.65,
            score_c: 0.44,
            score_final: 0.49,
            rejection_reason_codes: ['analyst_divergence_high'],
            rejection_reason_text: 'divergence high',
          },
        ],
      },
      feedback_options: {
        allowed_tags: ['threshold_false_negative', 'thesis_clear'],
        allowed_review_statuses: ['draft', 'final', 'adjudicated'],
      },
    };
    const batchRefreshedDayDetail: ReplaySelectionArtifactDay = {
      ...batchInitialDayDetail,
      feedback_record_count: 2,
      feedback_records: [
        {
          feedback_version: 'v1',
          artifact_version: 'v1',
          label_version: 'v1',
          run_id: 'run-1',
          trade_date: '2026-03-23',
          symbol: '300724',
          review_scope: 'watchlist',
          reviewer: 'einstein',
          review_status: 'final',
          primary_tag: 'threshold_false_negative',
          tags: ['threshold_false_negative', 'thesis_clear'],
          confidence: 0.77,
          research_verdict: 'needs_weekly_review',
          notes: 'weekly batch triage',
          created_at: '2026-03-23T12:00:00+08:00',
        },
        {
          feedback_version: 'v1',
          artifact_version: 'v1',
          label_version: 'v1',
          run_id: 'run-1',
          trade_date: '2026-03-23',
          symbol: '002916',
          review_scope: 'near_miss',
          reviewer: 'einstein',
          review_status: 'final',
          primary_tag: 'threshold_false_negative',
          tags: ['threshold_false_negative', 'thesis_clear'],
          confidence: 0.77,
          research_verdict: 'needs_weekly_review',
          notes: 'weekly batch triage',
          created_at: '2026-03-23T12:00:00+08:00',
        },
      ],
      feedback_summary: {
        label_version: 'v1',
        feedback_count: 2,
        final_feedback_count: 2,
        symbols: ['300724', '002916'],
        reviewers: ['einstein'],
        primary_tag_counts: {
          threshold_false_negative: 2,
        },
        tag_counts: {
          threshold_false_negative: 2,
          thesis_clear: 2,
        },
        review_status_counts: {
          final: 2,
        },
        verdict_counts: {
          needs_weekly_review: 2,
        },
        latest_created_at: '2026-03-23T12:00:00+08:00',
      },
    };

    listMock.mockResolvedValue(reports);
    getMock.mockResolvedValueOnce(detail).mockResolvedValueOnce(detailAfterBatchAppend);
    getSelectionArtifactDayMock.mockResolvedValueOnce(batchInitialDayDetail).mockResolvedValueOnce(batchRefreshedDayDetail);
    getFeedbackActivityMock.mockResolvedValueOnce({
      report_name: 'paper_trading_window_recent',
      reviewer: null,
      limit: 8,
      record_count: 0,
      recent_records: [],
      review_status_counts: {},
      tag_counts: {},
      reviewer_counts: {},
      report_counts: {},
    }).mockResolvedValueOnce({
      report_name: 'paper_trading_window_recent',
      reviewer: null,
      limit: 8,
      record_count: 2,
      recent_records: batchRefreshedDayDetail.feedback_records.map((record) => ({
        report_name: 'paper_trading_window_recent',
        trade_date: record.trade_date,
        symbol: record.symbol,
        review_scope: record.review_scope,
        reviewer: record.reviewer,
        review_status: record.review_status,
        primary_tag: record.primary_tag,
        tags: record.tags,
        confidence: record.confidence,
        research_verdict: record.research_verdict,
        notes: record.notes,
        created_at: record.created_at,
        feedback_path: '/tmp/replay/selection_artifacts/2026-03-23/research_feedback.jsonl',
      })),
      review_status_counts: { final: 2 },
      tag_counts: { threshold_false_negative: 2, thesis_clear: 2 },
      reviewer_counts: { einstein: 2 },
      report_counts: { paper_trading_window_recent: 2 },
    });
    getWorkflowQueueMock.mockResolvedValueOnce({
      assignee: 'einstein',
      workflow_status: null,
      report_name: null,
      limit: 12,
      item_count: 0,
      items: [],
      workflow_status_counts: {},
      assignee_counts: {},
      report_counts: {},
    }).mockResolvedValueOnce({
      assignee: 'einstein',
      workflow_status: null,
      report_name: null,
      limit: 12,
      item_count: 2,
      items: [
        {
          report_name: 'paper_trading_window_recent',
          trade_date: '2026-03-23',
          symbol: '300724',
          review_scope: 'watchlist',
          feedback_path: '/tmp/replay/selection_artifacts/2026-03-23/research_feedback.jsonl',
          latest_feedback_created_at: '2026-03-23T12:00:00+08:00',
          latest_reviewer: 'einstein',
          latest_review_status: 'final',
          latest_primary_tag: 'threshold_false_negative',
          latest_tags: ['threshold_false_negative', 'thesis_clear'],
          latest_research_verdict: 'needs_weekly_review',
          latest_notes: 'weekly batch triage',
          assignee: null,
          workflow_status: 'ready_for_adjudication',
        },
        {
          report_name: 'paper_trading_window_recent',
          trade_date: '2026-03-23',
          symbol: '002916',
          review_scope: 'near_miss',
          feedback_path: '/tmp/replay/selection_artifacts/2026-03-23/research_feedback.jsonl',
          latest_feedback_created_at: '2026-03-23T12:00:00+08:00',
          latest_reviewer: 'einstein',
          latest_review_status: 'final',
          latest_primary_tag: 'threshold_false_negative',
          latest_tags: ['threshold_false_negative', 'thesis_clear'],
          latest_research_verdict: 'needs_weekly_review',
          latest_notes: 'weekly batch triage',
          assignee: null,
          workflow_status: 'ready_for_adjudication',
        },
      ],
      workflow_status_counts: { ready_for_adjudication: 2 },
      assignee_counts: { __unassigned__: 2 },
      report_counts: { paper_trading_window_recent: 2 },
    });
    appendSelectionFeedbackBatchMock.mockResolvedValue({
      records: batchRefreshedDayDetail.feedback_records,
      appended_count: 2,
      feedback_record_count: 2,
      feedback_summary: batchRefreshedDayDetail.feedback_summary,
      directory_summary: {},
      feedback_path: '/tmp/replay/selection_artifacts/2026-03-23/research_feedback.jsonl',
    });

    render(<ReplayArtifactsSettings mode="workspace" />);

    await waitFor(() => {
      expect(getSelectionArtifactDayMock).toHaveBeenCalledWith('paper_trading_window_recent', '2026-03-23');
    });
    await screen.findByText('Batch Label Workspace');

    await user.click(screen.getByLabelText('[watchlist] 300724'));
    await user.click(screen.getByLabelText('[near_miss] 002916'));
    expect(screen.getByText((_, element) => element?.textContent === '2 selected')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Batch Primary Tag'), 'threshold_false_negative');
    await user.type(screen.getByLabelText('Batch Additional Tags'), 'thesis_clear');
    await user.selectOptions(screen.getByLabelText('Batch Review Status'), 'final');
    await user.clear(screen.getByLabelText('Batch Research Verdict'));
    await user.type(screen.getByLabelText('Batch Research Verdict'), 'needs_weekly_review');
    await user.clear(screen.getByLabelText('Batch Confidence'));
    await user.type(screen.getByLabelText('Batch Confidence'), '0.77');
    await user.type(screen.getByLabelText('Batch Notes'), 'weekly batch triage');
    await user.click(screen.getByRole('button', { name: 'Append Batch Feedback' }));

    await waitFor(() => {
      expect(appendSelectionFeedbackBatchMock).toHaveBeenCalledWith('paper_trading_window_recent', '2026-03-23', {
        symbols: ['300724', '002916'],
        primary_tag: 'threshold_false_negative',
        research_verdict: 'needs_weekly_review',
        tags: ['thesis_clear'],
        review_status: 'final',
        confidence: 0.77,
        notes: 'weekly batch triage',
      });
    });

    await waitFor(() => {
      expect(getMock).toHaveBeenCalledTimes(2);
      expect(getSelectionArtifactDayMock).toHaveBeenCalledTimes(2);
      expect(getFeedbackActivityMock).toHaveBeenCalledTimes(2);
      expect(getWorkflowQueueMock).toHaveBeenCalledTimes(2);
    });

    expect(screen.getByText('2 recent records')).toBeInTheDocument();
    expect(screen.getByText('status final:2')).toBeInTheDocument();
  });

  it('assigns an unowned workflow queue item to the current user', async () => {
    const user = userEvent.setup();
    listMock.mockResolvedValue(reports);
    getMock.mockResolvedValue(detail);
    getSelectionArtifactDayMock.mockResolvedValue({
      ...dayDetail,
      snapshot: {
        ...dayDetail.snapshot,
        selected: [
          {
            symbol: '300724',
            name: '捷佳伟创',
            decision: 'watchlist',
            score_b: 0.71,
            score_c: 0.63,
            score_final: 0.68,
            rank_in_watchlist: 1,
          },
        ],
      },
    });
    getFeedbackActivityMock.mockResolvedValue({
      report_name: 'paper_trading_window_recent',
      reviewer: null,
      limit: 8,
      record_count: 0,
      recent_records: [],
      review_status_counts: {},
      tag_counts: {},
      reviewer_counts: {},
      report_counts: {},
    });
    getWorkflowQueueMock.mockResolvedValueOnce({
      assignee: 'einstein',
      workflow_status: null,
      report_name: null,
      limit: 12,
      item_count: 1,
      items: [
        {
          report_name: 'paper_trading_window_recent',
          trade_date: '2026-03-23',
          symbol: '300724',
          review_scope: 'watchlist',
          feedback_path: '/tmp/replay/selection_artifacts/2026-03-23/research_feedback.jsonl',
          latest_feedback_created_at: '2026-03-23T10:00:00+08:00',
          latest_reviewer: 'einstein',
          latest_review_status: 'draft',
          latest_primary_tag: 'high_quality_selection',
          latest_tags: ['high_quality_selection'],
          latest_research_verdict: 'selected_for_good_reason',
          latest_notes: 'needs owner',
          assignee: null,
          workflow_status: 'unassigned',
        },
      ],
      workflow_status_counts: { unassigned: 1 },
      assignee_counts: { __unassigned__: 1 },
      report_counts: { paper_trading_window_recent: 1 },
    }).mockResolvedValueOnce({
      assignee: 'einstein',
      workflow_status: null,
      report_name: null,
      limit: 12,
      item_count: 1,
      items: [
        {
          report_name: 'paper_trading_window_recent',
          trade_date: '2026-03-23',
          symbol: '300724',
          review_scope: 'watchlist',
          feedback_path: '/tmp/replay/selection_artifacts/2026-03-23/research_feedback.jsonl',
          latest_feedback_created_at: '2026-03-23T10:00:00+08:00',
          latest_reviewer: 'einstein',
          latest_review_status: 'draft',
          latest_primary_tag: 'high_quality_selection',
          latest_tags: ['high_quality_selection'],
          latest_research_verdict: 'selected_for_good_reason',
          latest_notes: 'needs owner',
          assignee: 'einstein',
          workflow_status: 'assigned',
        },
      ],
      workflow_status_counts: { assigned: 1 },
      assignee_counts: { einstein: 1 },
      report_counts: { paper_trading_window_recent: 1 },
    });
    updateWorkflowQueueItemMock.mockResolvedValue({
      report_name: 'paper_trading_window_recent',
      trade_date: '2026-03-23',
      symbol: '300724',
      review_scope: 'watchlist',
      feedback_path: '/tmp/replay/selection_artifacts/2026-03-23/research_feedback.jsonl',
      latest_feedback_created_at: '2026-03-23T10:00:00+08:00',
      latest_reviewer: 'einstein',
      latest_review_status: 'draft',
      latest_primary_tag: 'high_quality_selection',
      latest_tags: ['high_quality_selection'],
      latest_research_verdict: 'selected_for_good_reason',
      latest_notes: 'needs owner',
      assignee: 'einstein',
      workflow_status: 'assigned',
    });

    render(<ReplayArtifactsSettings mode="workspace" />);

    await screen.findByText('Cross-Report Workflow Queue');
    await user.click(screen.getByRole('button', { name: 'Open Context' }));

    expect(screen.getByText('focus 300724')).toBeInTheDocument();
    expect(screen.getByDisplayValue('300724')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Assign to me' }));

    await waitFor(() => {
      expect(updateWorkflowQueueItemMock).toHaveBeenCalledWith({
        report_name: 'paper_trading_window_recent',
        trade_date: '2026-03-23',
        symbol: '300724',
        review_scope: 'watchlist',
        assignee: 'einstein',
        workflow_status: 'assigned',
      });
    });

    await waitFor(() => {
      expect(getWorkflowQueueMock).toHaveBeenCalledTimes(2);
    });

    expect(screen.getByText('assigned:1')).toBeInTheDocument();
    expect(screen.getByText('assignee einstein | reviewer einstein')).toBeInTheDocument();
  });
});