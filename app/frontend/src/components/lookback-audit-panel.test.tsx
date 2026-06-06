import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { LookbackAuditPanel } from '@/components/lookback-audit-panel';

vi.mock('@/services/lookback-audit-api', () => ({
  fetchLookbackAudit: vi.fn(),
}));

import { fetchLookbackAudit } from '@/services/lookback-audit-api';

const mockedFetch = vi.mocked(fetchLookbackAudit);

const baseResponse = {
  audit_date: '2026-05-01',
  lookforward_days: 30,
  selected_count: 3,
  audited_count: 3,
  ticker_results: [
    {
      ticker: '000001',
      rank: 1,
      score_final: 0.85,
      entry_date: '2026-05-01',
      entry_price: 10.0,
      exit_date: '2026-05-30',
      exit_price: 12.0,
      return_pct: 20.0,
      max_drawdown_pct: -3.5,
      max_return_pct: 22.4,
      trading_days_held: 21,
      data_status: 'ok',
    },
    {
      ticker: '000002',
      rank: 2,
      score_final: 0.72,
      entry_date: '2026-05-01',
      entry_price: 25.0,
      exit_date: '2026-05-30',
      exit_price: 22.5,
      return_pct: -10.0,
      max_drawdown_pct: -12.0,
      max_return_pct: 4.0,
      trading_days_held: 21,
      data_status: 'ok',
    },
    {
      ticker: '000003',
      rank: 3,
      score_final: 0.6,
      entry_date: '2026-05-01',
      entry_price: 8.0,
      exit_date: null,
      exit_price: null,
      return_pct: null,
      max_drawdown_pct: null,
      max_return_pct: null,
      trading_days_held: 0,
      data_status: 'missing',
    },
  ],
  summary: {
    hit_rate: 0.5,
    avg_return_pct: 3.33,
    best_return_pct: 20.0,
    worst_return_pct: -10.0,
    median_return_pct: -3.0,
  },
};

beforeEach(() => {
  mockedFetch.mockReset();
});

describe('LookbackAuditPanel (NEW-B)', () => {
  it('renders the panel header and controls on mount', () => {
    mockedFetch.mockResolvedValueOnce(baseResponse);
    render(<LookbackAuditPanel defaultDate="2026-05-01" />);
    expect(screen.getByTestId('lookback-audit-panel')).toBeTruthy();
    expect(screen.getByText(/30-Day Lookback Audit/)).toBeTruthy();
    expect(screen.getByTestId('lookback-date-input')).toBeTruthy();
    expect(screen.getByTestId('lookback-days-input')).toBeTruthy();
    expect(screen.getByTestId('lookback-topn-input')).toBeTruthy();
    expect(screen.getByTestId('lookback-run-button')).toBeTruthy();
  });

  it('auto-loads data on mount and renders the headline + table', async () => {
    mockedFetch.mockResolvedValueOnce(baseResponse);
    render(<LookbackAuditPanel defaultDate="2026-05-01" />);

    await waitFor(() => {
      expect(screen.getByTestId('lookback-headline')).toBeTruthy();
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      expect.objectContaining({ date: '2026-05-01', days: 30, topN: 10 }),
    );
    expect(screen.getByTestId('lookback-hit-rate').textContent).toContain('50%');
    expect(screen.getByTestId('lookback-avg-return').textContent).toContain('+3.33%');
    // 3 ticker rows
    const rows = screen.getAllByTestId('lookback-ticker-row');
    expect(rows).toHaveLength(3);
    // First row: positive return
    expect(rows[0].getAttribute('data-ticker')).toBe('000001');
    expect(screen.getAllByTestId('lookback-return')[0].textContent).toContain('+20.00%');
  });

  it('reloads when the user changes inputs and clicks Run audit', async () => {
    mockedFetch.mockResolvedValueOnce(baseResponse);
    render(<LookbackAuditPanel defaultDate="2026-05-01" />);

    await waitFor(() => {
      expect(screen.getByTestId('lookback-headline')).toBeTruthy();
    });

    // Use fireEvent.change to set the input value atomically (avoids the
    // intermediate onChange calls that userEvent.type produces while the
    // field is being cleared).
    const daysInput = screen.getByTestId('lookback-days-input');
    fireEvent.change(daysInput, { target: { value: '60' } });
    expect((daysInput as HTMLInputElement).value).toBe('60');

    mockedFetch.mockResolvedValueOnce({ ...baseResponse, lookforward_days: 60 });
    fireEvent.click(screen.getByTestId('lookback-run-button'));

    await waitFor(() => {
      expect(mockedFetch).toHaveBeenCalledTimes(2);
    });
    const secondCall = mockedFetch.mock.calls[1][0];
    expect(secondCall.days).toBe(60);
  });

  it('renders the error banner when the API fails', async () => {
    mockedFetch.mockRejectedValueOnce(new Error('selection_snapshot not found'));
    render(<LookbackAuditPanel defaultDate="2026-05-01" />);
    await waitFor(() => {
      expect(screen.getByTestId('lookback-error')).toBeTruthy();
    });
    expect(screen.getByTestId('lookback-error').textContent).toContain(
      'selection_snapshot not found',
    );
  });

  it('renders the empty state when the audit returns no tickers', async () => {
    mockedFetch.mockResolvedValueOnce({
      ...baseResponse,
      selected_count: 0,
      audited_count: 0,
      ticker_results: [],
    });
    render(<LookbackAuditPanel defaultDate="2026-05-01" />);
    await waitFor(() => {
      expect(screen.getByTestId('lookback-empty')).toBeTruthy();
    });
  });

  it('formats return colors: positive green, negative red', async () => {
    mockedFetch.mockResolvedValueOnce(baseResponse);
    render(<LookbackAuditPanel defaultDate="2026-05-01" />);
    await waitFor(() => {
      expect(screen.getAllByTestId('lookback-return')).toHaveLength(3);
    });
    const returns = screen.getAllByTestId('lookback-return');
    expect(returns[0].className).toContain('text-green-500');
    expect(returns[1].className).toContain('text-red-500');
    // Third ticker has null return
    expect(returns[2].textContent).toBe('--');
  });
});
