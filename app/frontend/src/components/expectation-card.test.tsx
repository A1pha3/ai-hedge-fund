import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import {
  ExpectationCard,
  type StockHistoryExpectationData,
} from '@/components/expectation-card';

const baseData: StockHistoryExpectationData = {
  ticker: '000001',
  n_trades: 12,
  win_rate: 0.6,
  avg_30d_return: 3.5,
  worst_30d_return: -4.2,
  best_30d_return: 12.4,
  is_small_sample: false,
  lookback_days: 60,
  period_start: '2026-04-01',
  period_end: '2026-05-31',
};

describe('ExpectationCard (OPT-C)', () => {
  it('renders ticker, win rate, average and worst return', () => {
    render(<ExpectationCard data={baseData} />);
    expect(screen.getByTestId('expectation-card')).toBeTruthy();
    expect(screen.getByText('000001 30-Day Expectation')).toBeTruthy();
    expect(screen.getByTestId('expectation-win-rate').textContent).toContain('60.0%');
    expect(screen.getByTestId('expectation-avg-return').textContent).toContain('+3.50%');
    expect(screen.getByTestId('expectation-worst').textContent).toContain('-4.20%');
    expect(screen.getByTestId('expectation-best').textContent).toContain('+12.40%');
  });

  it('marks small-sample state with a warning banner and amber sample badge', () => {
    const small = { ...baseData, n_trades: 3, is_small_sample: true };
    render(<ExpectationCard data={small} />);
    const card = screen.getByTestId('expectation-card');
    expect(card.getAttribute('data-small-sample')).toBe('true');
    expect(screen.getByTestId('small-sample-warning')).toBeTruthy();
    expect(screen.getByTestId('expectation-sample-badge').textContent).toContain('小样本');
  });

  it('falls back to em-dash when fields are null (unwired backend)', () => {
    const empty = {
      ...baseData,
      win_rate: null,
      avg_30d_return: null,
      worst_30d_return: null,
      best_30d_return: null,
      n_trades: 0,
      is_small_sample: true,
    };
    render(<ExpectationCard data={empty} />);
    expect(screen.getByTestId('expectation-win-rate').textContent).toBe('--');
    expect(screen.getByTestId('expectation-avg-return').textContent).toBe('--');
    expect(screen.getByTestId('expectation-worst').textContent).toBe('--');
    expect(screen.getByTestId('expectation-best').textContent).toBe('--');
  });

  it('uses a "reliable" sample badge when n_trades >= 5', () => {
    render(<ExpectationCard data={baseData} />);
    expect(screen.getByTestId('expectation-sample-badge').textContent).toContain('n=12');
    expect(screen.getByTestId('expectation-sample-badge').textContent).toContain('可靠');
  });

  it('formats the lookback window in the description', () => {
    render(<ExpectationCard data={baseData} />);
    expect(screen.getByText(/12 笔成交/)).toBeTruthy();
    expect(screen.getByText(/60 日窗口/)).toBeTruthy();
    expect(screen.getByText(/2026-04-01/)).toBeTruthy();
  });
});
