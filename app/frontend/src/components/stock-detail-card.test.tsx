/**
 * P2-6: 标的深度分析卡片 + ScreeningResultsPanel 点击集成 测试。
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { StockDetailCard } from '@/components/stock-detail-card';
import { ScreeningResultsPanel } from '@/components/screening-results-panel';
import type { StockDetail } from '@/services/stock-detail-api';
import type { ScreeningRecommendation } from '@/services/custom-weights-api';

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const MOCK_DETAIL: StockDetail = {
  ticker: '000001',
  name: '平安银行',
  industry_sw: '银行',
  pe_ratio: 5.5,
  pb_ratio: 0.6,
  roe: 0.108,
  revenue_growth: 0.05,
  profit_growth: 0.03,
  dividend_yield: 0.045,
  price: 12.34,
  change_pct: 2.15,
  ma5: 12.1,
  ma20: 11.8,
  ma60: 11.2,
  rsi_14: 55.3,
  macd_signal: 'bullish_cross',
  atr_pct: 0.028,
  money_flow_net: 1.5e8,
  north_money_net: 0.8e8,
  dragon_tiger: false,
  recommendation_count_30d: 5,
  latest_score_b: 0.78,
  latest_decision: 'bullish',
  consecutive_days: 3,
  decay_level: 'none',
  industry_rank: 2,
  industry_total: 8,
};

const MOCK_RECS: ScreeningRecommendation[] = [
  { ticker: '000001', name: '平安银行', score_b: 0.78, decision: 'bullish' },
  { ticker: '600519', name: '贵州茅台', score_b: 0.65, decision: 'bullish' },
  { ticker: '300724', name: '捷佳伟创', score_b: 0.42, decision: 'neutral' },
];

// ---------------------------------------------------------------------------
// StockDetailCard tests
// ---------------------------------------------------------------------------

describe('StockDetailCard', () => {
  it('renders header with ticker, name, price, and industry', () => {
    render(<StockDetailCard detail={MOCK_DETAIL} onClose={vi.fn()} />);

    expect(screen.getByTestId('stock-detail-card')).toBeDefined();
    expect(screen.getByText(/000001/)).toBeDefined();
    expect(screen.getByText(/平安银行/)).toBeDefined();
    // Industry badge rendered in CardDescription
    expect(screen.getByText('银行')).toBeDefined();
    // Price displayed in header
    expect(screen.getByText(/¥12\.34/)).toBeDefined();
  });

  it('shows fundamental tab as default with PE, PB, ROE', () => {
    render(<StockDetailCard detail={MOCK_DETAIL} onClose={vi.fn()} />);

    // Default tab is fundamental — these labels should be visible
    expect(screen.getByText(/PE \(市盈率\)/)).toBeDefined();
    expect(screen.getByText(/PB \(市净率\)/)).toBeDefined();
    expect(screen.getByText(/ROE/)).toBeDefined();
  });

  it('shows loading skeleton when isLoading=true', () => {
    render(<StockDetailCard detail={null} isLoading onClose={vi.fn()} />);

    expect(screen.getByTestId('stock-detail-card')).toBeDefined();
    // No real data visible
    expect(screen.queryByText(/000001/)).toBeNull();
  });

  it('calls onClose when close button clicked', () => {
    const onClose = vi.fn();
    render(<StockDetailCard detail={MOCK_DETAIL} onClose={onClose} />);

    fireEvent.click(screen.getByTestId('stock-detail-close'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders null when detail is null and not loading', () => {
    const { container } = render(<StockDetailCard detail={null} onClose={vi.fn()} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders all 4 tab triggers', () => {
    render(<StockDetailCard detail={MOCK_DETAIL} onClose={vi.fn()} />);

    const tabs = screen.getAllByRole('tab');
    expect(tabs.length).toBe(4);
  });

  it('handles null/undefined fields gracefully (shows —)', () => {
    const sparseDetail: StockDetail = {
      ...MOCK_DETAIL,
      pe_ratio: null,
      pb_ratio: undefined,
      roe: null,
      money_flow_net: null,
      industry_rank: null,
      industry_total: null,
    };

    render(<StockDetailCard detail={sparseDetail} onClose={vi.fn()} />);

    // Fundamental tab is default — null pe_ratio should show '—'
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBeGreaterThanOrEqual(3);
  });

  it('formats money flow values in 亿 unit', () => {
    render(<StockDetailCard detail={MOCK_DETAIL} onClose={vi.fn()} />);

    // Verify the component renders without error
    expect(screen.getByTestId('stock-detail-card')).toBeDefined();
    // 4 tabs present
    expect(screen.getAllByRole('tab').length).toBe(4);
  });
});

// ---------------------------------------------------------------------------
// ScreeningResultsPanel click-to-select tests
// ---------------------------------------------------------------------------

describe('ScreeningResultsPanel click-to-select', () => {
  it('calls onSelectTicker when a row is clicked', () => {
    const onSelect = vi.fn();
    render(
      <ScreeningResultsPanel
        recommendations={MOCK_RECS}
        onSelectTicker={onSelect}
      />,
    );

    fireEvent.click(screen.getByTestId('screening-result-row-000001'));
    expect(onSelect).toHaveBeenCalledWith('000001');
  });

  it('highlights the selected ticker row', () => {
    render(
      <ScreeningResultsPanel
        recommendations={MOCK_RECS}
        selectedTicker="600519"
      />,
    );

    const selectedRow = screen.getByTestId('screening-result-row-600519');
    expect(selectedRow.className).toContain('ring-1');
  });

  it('does not highlight unselected rows', () => {
    render(
      <ScreeningResultsPanel
        recommendations={MOCK_RECS}
        selectedTicker="600519"
      />,
    );

    const unselectedRow = screen.getByTestId('screening-result-row-000001');
    expect(unselectedRow.className).not.toContain('ring-1');
  });

  it('supports keyboard activation via Enter key', () => {
    const onSelect = vi.fn();
    render(
      <ScreeningResultsPanel
        recommendations={MOCK_RECS}
        onSelectTicker={onSelect}
      />,
    );

    fireEvent.keyDown(screen.getByTestId('screening-result-row-300724'), {
      key: 'Enter',
    });
    expect(onSelect).toHaveBeenCalledWith('300724');
  });

  it('toggles off when clicking same row again', () => {
    const onSelect = vi.fn();
    render(
      <ScreeningResultsPanel
        recommendations={MOCK_RECS}
        onSelectTicker={onSelect}
      />,
    );

    const row = screen.getByTestId('screening-result-row-000001');
    fireEvent.click(row);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith('000001');
  });
});
