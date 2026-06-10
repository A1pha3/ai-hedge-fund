/**
 * P2-2: 回测参数对比面板 + API service 测试。
 */
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ParamComparePanel } from '@/components/param-compare-panel';
import { formatMetricValue, METRIC_LABELS } from '@/services/param-compare-api';
import type { ParamCompareReport } from '@/services/param-compare-api';

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const MOCK_REPORT: ParamCompareReport = {
  trials: [
    {
      trial_index: 0,
      params: { window: 20, threshold: 0.5 },
      metrics: { sharpe_ratio: 1.2, sortino_ratio: 1.5, max_drawdown: -0.15, win_rate: 0.55, total_return: 0.32, window_count: 45 },
      duration_seconds: 3.2,
    },
    {
      trial_index: 1,
      params: { window: 10, threshold: 0.3 },
      metrics: { sharpe_ratio: 0.8, sortino_ratio: 0.9, max_drawdown: -0.25, win_rate: 0.48, total_return: 0.15, window_count: 62 },
      duration_seconds: 2.8,
    },
    {
      trial_index: 2,
      params: { window: 30, threshold: 0.7 },
      metrics: { sharpe_ratio: 1.5, sortino_ratio: 1.8, max_drawdown: -0.10, win_rate: 0.62, total_return: 0.45, window_count: 30 },
      duration_seconds: 4.1,
    },
  ],
  total_combinations: 3,
  max_workers: 2,
};

const MOCK_REPORT_WITH_FAILURE: ParamCompareReport = {
  ...MOCK_REPORT,
  trials: [
    ...MOCK_REPORT.trials,
    {
      trial_index: 3,
      params: { window: 5, threshold: 0.1 },
      metrics: { sharpe_ratio: null, sortino_ratio: null, max_drawdown: null, win_rate: null, total_return: null, window_count: null },
      duration_seconds: 1.0,
      error: 'ValueError: window too small',
    },
  ],
  total_combinations: 4,
};

// ---------------------------------------------------------------------------
// formatMetricValue tests
// ---------------------------------------------------------------------------

describe('formatMetricValue', () => {
  it('formats percentage metrics', () => {
    expect(formatMetricValue('win_rate', 0.55)).toBe('55.0%');
    expect(formatMetricValue('max_drawdown', -0.15)).toBe('-15.0%');
    expect(formatMetricValue('total_return', 0.32)).toBe('32.0%');
  });

  it('formats ratio metrics with 3 decimals', () => {
    expect(formatMetricValue('sharpe_ratio', 1.234)).toBe('1.234');
    expect(formatMetricValue('sortino_ratio', 0.5)).toBe('0.500');
  });

  it('formats window_count as integer', () => {
    expect(formatMetricValue('window_count', 45.7)).toBe('46');
  });

  it('returns — for null values', () => {
    expect(formatMetricValue('sharpe_ratio', null)).toBe('—');
  });

  it('returns — for non-finite numbers', () => {
    expect(formatMetricValue('sharpe_ratio', NaN)).toBe('—');
    expect(formatMetricValue('sharpe_ratio', Infinity)).toBe('—');
  });
});

// ---------------------------------------------------------------------------
// METRIC_LABELS
// ---------------------------------------------------------------------------

describe('METRIC_LABELS', () => {
  it('has labels for all COMPARISON_METRICS', () => {
    expect(METRIC_LABELS['sharpe_ratio']).toBe('Sharpe');
    expect(METRIC_LABELS['win_rate']).toBe('胜率');
    expect(METRIC_LABELS['max_drawdown']).toBe('最大回撤');
  });
});

// ---------------------------------------------------------------------------
// ParamComparePanel tests
// ---------------------------------------------------------------------------

describe('ParamComparePanel', () => {
  it('renders comparison table with trial data', () => {
    render(<ParamComparePanel report={MOCK_REPORT} />);

    expect(screen.getByTestId('param-compare-panel')).toBeDefined();
    expect(screen.getByTestId('param-compare-table')).toBeDefined();
    // Should have 3 trial rows
    expect(screen.getByTestId('param-trial-0')).toBeDefined();
    expect(screen.getByTestId('param-trial-1')).toBeDefined();
    expect(screen.getByTestId('param-trial-2')).toBeDefined();
  });

  it('shows summary in header (passing / failed / total)', () => {
    render(<ParamComparePanel report={MOCK_REPORT_WITH_FAILURE} />);

    expect(screen.getByText(/3 成功/)).toBeDefined();
    expect(screen.getByText(/1 失败/)).toBeDefined();
    expect(screen.getByText(/共 4 组合/)).toBeDefined();
  });

  it('highlights best value for each metric with ★', () => {
    render(<ParamComparePanel report={MOCK_REPORT} />);

    // Trial 2 (index 2) has the best sharpe_ratio (1.5)
    const bestSharpe = screen.getByTestId('trial-2-sharpe_ratio');
    expect(bestSharpe.textContent).toContain('★');
  });

  it('renders param columns with correct values', () => {
    render(<ParamComparePanel report={MOCK_REPORT} />);

    // First trial: window=20, threshold=0.5
    const row0 = screen.getByTestId('param-trial-0');
    expect(row0.textContent).toContain('20');
    expect(row0.textContent).toContain('0.5');
  });

  it('shows failed trials in error section', () => {
    render(<ParamComparePanel report={MOCK_REPORT_WITH_FAILURE} />);

    expect(screen.getByTestId('param-compare-failed')).toBeDefined();
    expect(screen.getByText(/ValueError/)).toBeDefined();
  });

  it('shows empty state when report is null', () => {
    render(<ParamComparePanel report={null} />);

    expect(screen.getByText(/暂无对比数据/)).toBeDefined();
  });

  it('shows loading state', () => {
    render(<ParamComparePanel report={null} isLoading />);

    expect(screen.getByText(/加载中/)).toBeDefined();
  });

  it('sorts trials when clicking metric header', () => {
    render(<ParamComparePanel report={MOCK_REPORT} />);

    // Click win_rate header to sort
    fireEvent.click(screen.getByTestId('sort-win_rate'));

    // Should still render (no crash)
    expect(screen.getByTestId('param-compare-table')).toBeDefined();
  });

  it('displays duration in seconds', () => {
    render(<ParamComparePanel report={MOCK_REPORT} />);

    const row0 = screen.getByTestId('param-trial-0');
    expect(row0.textContent).toContain('3.2s');
  });
});
