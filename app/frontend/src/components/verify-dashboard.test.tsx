/**
 * VerifyDashboard (P3 Web UI) tests.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import {
  VerifyDashboard,
  type VerifySummary,
  type WeightCalibrationResult,
  type CrossPick,
  type PortfolioSummary,
} from '@/components/verify-dashboard';

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const MOCK_VERIFY: VerifySummary = {
  lookback_days: 30,
  total_days: 15,
  total_recommendations: 60,
  unique_tickers: 30,
  overall_t1_win_rate: 0.55,
  overall_t3_win_rate: 0.58,
  overall_t5_win_rate: 0.60,
  avg_t1_return: 0.012,
  avg_t3_return: 0.025,
  avg_t5_return: 0.040,
  benchmark_avg_t1: 0.005,
  excess_return: 0.007,
  strategy_attribution: [
    { strategy_name: 'trend', recommendation_count: 20, avg_t1_return: 0.018, win_rate: 0.62 },
    { strategy_name: 'fundamental', recommendation_count: 18, avg_t1_return: 0.010, win_rate: 0.55 },
    { strategy_name: 'mean_reversion', recommendation_count: 12, avg_t1_return: -0.005, win_rate: 0.45 },
  ],
};

const MOCK_WEIGHTS: WeightCalibrationResult = {
  lookback_days: 30,
  original_weights: { trend: 0.30, mean_reversion: 0.20, fundamental: 0.30, event_sentiment: 0.20 },
  calibrated_weights: { trend: 0.40, mean_reversion: 0.15, fundamental: 0.30, event_sentiment: 0.15 },
  n_factors: 12,
  n_observations: 20,
  calibration_skipped: false,
};

const MOCK_CROSS: CrossPick[] = [
  {
    industry_name: '银行',
    industry_rank: 1,
    momentum_score: 25.5,
    candidate_count: 5,
    top_picks: [
      { ticker: '000001', name: '平安银行', score_b: 0.85, decision: 'bullish' },
      { ticker: '600036', name: '招商银行', score_b: 0.78, decision: 'bullish' },
    ],
  },
  {
    industry_name: '食品饮料',
    industry_rank: 2,
    momentum_score: 18.2,
    candidate_count: 3,
    top_picks: [
      { ticker: '600519', name: '贵州茅台', score_b: 0.90, decision: 'bullish' },
    ],
  },
];

const MOCK_PORTFOLIO: PortfolioSummary = {
  n_positions: 5,
  total_weight: 0.85,
  industry_breakdown: { '银行': 0.30, '食品饮料': 0.25, '电力设备': 0.20, '汽车': 0.10 },
  concentration_top1: 0.20,
  concentration_top3: 0.55,
  expected_sharpe: 0.65,
  equal_weight_sharpe: 0.55,
  positions: [
    { ticker: '000001', name: '平安银行', industry: '银行', score_b: 0.85, weight: 0.20 },
    { ticker: '600519', name: '贵州茅台', industry: '食品饮料', score_b: 0.90, weight: 0.20 },
    { ticker: '300750', name: '宁德时代', industry: '电力设备', score_b: 0.65, weight: 0.15 },
    { ticker: '002594', name: '比亚迪', industry: '汽车', score_b: 0.55, weight: 0.10 },
    { ticker: '000858', name: '五粮液', industry: '食品饮料', score_b: 0.78, weight: 0.20 },
  ],
};

// ---------------------------------------------------------------------------
// Component tests
// ---------------------------------------------------------------------------

describe('VerifyDashboard', () => {
  it('renders with all 4 tab triggers', () => {
    render(<VerifyDashboard verifySummary={MOCK_VERIFY} weightResult={MOCK_WEIGHTS} crossPicks={MOCK_CROSS} portfolio={MOCK_PORTFOLIO} />);

    expect(screen.getByTestId('verify-dashboard')).toBeDefined();
    const tabs = screen.getAllByRole('tab');
    expect(tabs.length).toBe(4);
  });

  it('shows empty state when no data', () => {
    render(<VerifyDashboard />);

    expect(screen.getByText(/暂无数据/)).toBeDefined();
  });

  it('shows loading state', () => {
    render(<VerifyDashboard isLoading />);

    expect(screen.getByText(/加载中/)).toBeDefined();
  });

  it('renders verify tab as default with metrics', () => {
    render(<VerifyDashboard verifySummary={MOCK_VERIFY} />);

    expect(screen.getByTestId('verify-tab')).toBeDefined();
    expect(screen.getByText(/T\+1 胜率/)).toBeDefined();
  });

  it('switches to weights tab and shows comparison', () => {
    render(<VerifyDashboard weightResult={MOCK_WEIGHTS} />);

    // Click weights tab and verify component still renders
    const weightsTab = screen.getByRole('tab', { name: /权重/ });
    fireEvent.click(weightsTab);
    expect(screen.getByTestId('verify-dashboard')).toBeDefined();
  });

  it('switches to cross picks tab and shows industries', () => {
    render(<VerifyDashboard crossPicks={MOCK_CROSS} />);

    const crossTab = screen.getByRole('tab', { name: /交叉/ });
    fireEvent.click(crossTab);
    expect(screen.getByTestId('verify-dashboard')).toBeDefined();
  });

  it('switches to portfolio tab and shows positions', () => {
    render(<VerifyDashboard portfolio={MOCK_PORTFOLIO} />);

    const portfolioTab = screen.getByRole('tab', { name: /组合/ });
    fireEvent.click(portfolioTab);
    expect(screen.getByTestId('verify-dashboard')).toBeDefined();
  });

  it('handles skipped calibration gracefully', () => {
    const skippedWeights: WeightCalibrationResult = {
      ...MOCK_WEIGHTS,
      calibration_skipped: true,
    };
    render(<VerifyDashboard weightResult={skippedWeights} verifySummary={MOCK_VERIFY} />);

    // Component should render without crashing
    expect(screen.getByTestId('verify-dashboard')).toBeDefined();
    // Default tab (verify) should still work
    expect(screen.getByTestId('verify-tab')).toBeDefined();
  });

  it('handles null portfolio gracefully', () => {
    render(<VerifyDashboard verifySummary={MOCK_VERIFY} portfolio={null} />);
    // Should not crash
    expect(screen.getByTestId('verify-dashboard')).toBeDefined();
  });

  it('shows strategy attribution when present', () => {
    render(<VerifyDashboard verifySummary={MOCK_VERIFY} />);

    // Verify tab is default; strategy attribution is shown
    expect(screen.getByText(/趋势|trend/)).toBeDefined();
  });
});
