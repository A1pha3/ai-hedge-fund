/**
 * Tests for AdjustmentSimulator component (P2 2.3).
 *
 * Covers:
 * 1. Renders the trigger button and opens the dialog
 * 2. Displays all tickers with their planned actions
 * 3. Cancel/reduce toggle buttons work correctly
 * 4. Run simulation button is disabled when no adjustments
 * 5. Shows results after successful simulation
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { AdjustmentSimulator } from './adjustment-simulator';

// ---------- Fixtures ----------

const DECISIONS = {
  AAPL: { action: 'buy', quantity: 50, confidence: 80, reasoning: 'Strong fundamentals' },
  MSFT: { action: 'sell', quantity: 20, confidence: 70, reasoning: 'Overvalued' },
  NVDA: { action: 'hold', quantity: 0, confidence: 60, reasoning: 'Wait and see' },
};

const POSITIONS = {
  AAPL: { long: 100, short: 0, long_cost_basis: 180.0, short_cost_basis: 0.0 },
  MSFT: { long: 50, short: 0, long_cost_basis: 400.0, short_cost_basis: 0.0 },
  NVDA: { long: 30, short: 0, long_cost_basis: 500.0, short_cost_basis: 0.0 },
};

const PRICES = { AAPL: 190.0, MSFT: 420.0, NVDA: 510.0 };

const SIM_RESPONSE = {
  before: {
    hhi: 0.35,
    short_ratio: 0.0,
    cvar_95: 0.12,
    position_count: 3,
    max_single_position_weight: 0.45,
    total_nav: 155000.0,
    total_long: 55000.0,
    total_short: 0.0,
  },
  after: {
    hhi: 0.25,
    short_ratio: 0.0,
    cvar_95: 0.08,
    position_count: 2,
    max_single_position_weight: 0.35,
    total_nav: 152000.0,
    total_long: 52000.0,
    total_short: 0.0,
  },
  delta: {
    hhi: -0.1,
    short_ratio: 0.0,
    cvar_95: -0.04,
    position_count: -1,
    max_single_position_weight: -0.1,
    total_nav: -3000.0,
    total_long: -3000.0,
    total_short: 0.0,
  },
  ticker_results: [
    { ticker: 'AAPL', original_action: 'buy', simulated_action: 'hold', original_quantity: 50, simulated_quantity: 0, operation_applied: 'cancel', reduce_pct: 0 },
    { ticker: 'MSFT', original_action: 'sell', simulated_action: 'sell', original_quantity: 20, simulated_quantity: 10, operation_applied: 'reduce', reduce_pct: 0.5 },
    { ticker: 'NVDA', original_action: 'hold', simulated_action: 'hold', original_quantity: 0, simulated_quantity: 0, operation_applied: null, reduce_pct: 0 },
  ],
};

// ---------- Mocks ----------

const mockFetch = vi.fn();
global.fetch = mockFetch;

function mockFetchResponse(data: any, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(data),
  } as Response);
}

// ---------- Tests ----------

describe('AdjustmentSimulator — P2 2.3', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it('renders the trigger button and opens the dialog', async () => {
    render(
      <AdjustmentSimulator
        decisions={DECISIONS}
        positions={POSITIONS}
        currentPrices={PRICES}
        cash={100000}
      />,
    );

    // Trigger button exists
    expect(screen.getByTestId('simulator-trigger')).toBeDefined();
    expect(screen.getByText('Simulate Adjustments')).toBeDefined();

    // Click to open dialog
    fireEvent.click(screen.getByTestId('simulator-trigger'));

    await waitFor(() => {
      expect(screen.getByTestId('simulator-dialog')).toBeDefined();
    });

    // Title visible
    expect(screen.getByText('Adjustment Simulator')).toBeDefined();
  });

  it('displays all tickers with their planned actions in the table', async () => {
    render(
      <AdjustmentSimulator
        decisions={DECISIONS}
        positions={POSITIONS}
        currentPrices={PRICES}
        cash={100000}
      />,
    );

    // Open dialog
    fireEvent.click(screen.getByTestId('simulator-trigger'));

    await waitFor(() => {
      expect(screen.getByTestId('simulator-dialog')).toBeDefined();
    });

    // All tickers are shown
    expect(screen.getByTestId('simulator-row-AAPL')).toBeDefined();
    expect(screen.getByTestId('simulator-row-MSFT')).toBeDefined();
    expect(screen.getByTestId('simulator-row-NVDA')).toBeDefined();

    // Planned actions are shown as badges
    expect(screen.getByText(/BUY.*x50/)).toBeDefined();
    expect(screen.getByText(/SELL.*x20/)).toBeDefined();
  });

  it('cancel button toggles cancel state for a ticker', async () => {
    render(
      <AdjustmentSimulator
        decisions={DECISIONS}
        positions={POSITIONS}
        currentPrices={PRICES}
        cash={100000}
      />,
    );

    fireEvent.click(screen.getByTestId('simulator-trigger'));

    await waitFor(() => {
      expect(screen.getByTestId('simulator-dialog')).toBeDefined();
    });

    // Cancel AAPL
    const cancelBtn = screen.getByTestId('cancel-btn-AAPL');
    fireEvent.click(cancelBtn);

    // Button should now be destructive variant (active)
    expect(cancelBtn.classList.toString()).toContain('destructive');
  });

  it('reduce button shows percentage input and toggles correctly', async () => {
    render(
      <AdjustmentSimulator
        decisions={DECISIONS}
        positions={POSITIONS}
        currentPrices={PRICES}
        cash={100000}
      />,
    );

    fireEvent.click(screen.getByTestId('simulator-trigger'));

    await waitFor(() => {
      expect(screen.getByTestId('simulator-dialog')).toBeDefined();
    });

    // Initially no reduce input for MSFT
    expect(screen.queryByTestId('reduce-pct-MSFT')).toBeNull();

    // Click reduce for MSFT
    const reduceBtn = screen.getByTestId('reduce-btn-MSFT');
    fireEvent.click(reduceBtn);

    // Now the reduce input should appear
    expect(screen.getByTestId('reduce-pct-MSFT')).toBeDefined();
    expect(screen.getByTestId('reduce-pct-MSFT').getAttribute('value')).toBe('50');
  });

  it('run simulation button is disabled when no adjustments are made', async () => {
    render(
      <AdjustmentSimulator
        decisions={DECISIONS}
        positions={POSITIONS}
        currentPrices={PRICES}
        cash={100000}
      />,
    );

    fireEvent.click(screen.getByTestId('simulator-trigger'));

    await waitFor(() => {
      expect(screen.getByTestId('simulator-dialog')).toBeDefined();
    });

    // Run button should be disabled
    const runBtn = screen.getByTestId('run-simulation-btn');
    expect(runBtn).toBeDisabled();
  });

  it('shows results after successful simulation', async () => {
    mockFetch.mockReturnValue(mockFetchResponse(SIM_RESPONSE));

    render(
      <AdjustmentSimulator
        decisions={DECISIONS}
        positions={POSITIONS}
        currentPrices={PRICES}
        cash={100000}
      />,
    );

    fireEvent.click(screen.getByTestId('simulator-trigger'));

    await waitFor(() => {
      expect(screen.getByTestId('simulator-dialog')).toBeDefined();
    });

    // Make an adjustment
    fireEvent.click(screen.getByTestId('cancel-btn-AAPL'));

    // Run simulation
    const runBtn = screen.getByTestId('run-simulation-btn');
    expect(runBtn).not.toBeDisabled();
    fireEvent.click(runBtn);

    // Wait for results
    await waitFor(() => {
      expect(screen.getByTestId('sim-results')).toBeDefined();
    });

    // Metrics grid should be visible
    expect(screen.getByTestId('metrics-grid')).toBeDefined();

    // Specific metrics
    expect(screen.getByTestId('metric-hhi')).toBeDefined();
    expect(screen.getByTestId('metric-cvar-(95%)')).toBeDefined();
    expect(screen.getByTestId('metric-total-nav')).toBeDefined();

    // Per-ticker results
    expect(screen.getByTestId('result-row-AAPL')).toBeDefined();
    expect(screen.getByTestId('result-row-MSFT')).toBeDefined();
    expect(screen.getByTestId('result-row-NVDA')).toBeDefined();
  });
});
