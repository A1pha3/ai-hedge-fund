import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { EdgeCard, edgeColor, formatPct, formatRatio, riskBudgetVariant } from './edge-card';

describe('EdgeCard', () => {
  it('renders ticker, edge value, cvar, and risk budget ratio', () => {
    render(
      <EdgeCard
        ticker="AAPL"
        data={{
          expected_30d_edge: 7.5,
          cvar_95: 8.0, // value 8.0 -> '8.00%' (the formatter treats input as a percent)
          risk_budget_ratio: 0.65,
          edge_summary: 'Strong bullish momentum across all analysts.',
        }}
      />,
    );

    // Ticker is in the title
    expect(screen.getByText(/30D Edge — AAPL/)).toBeDefined();
    // Edge value appears twice (badge + value) — use getAllByText
    const positives = screen.getAllByText('+7.50%');
    expect(positives.length).toBeGreaterThan(0);
    // CVaR(95%) label and value (+8.00% because formatPct adds + for positive)
    expect(screen.getByText('CVaR(95%)')).toBeDefined();
    expect(screen.getByText('+8.00%')).toBeDefined();
    // Risk Budget Used is 65.00% (appears twice: label + value)
    const sixtyFive = screen.getAllByText('65.00%');
    expect(sixtyFive.length).toBeGreaterThan(0);
    // Summary is rendered
    expect(screen.getByText('Strong bullish momentum across all analysts.')).toBeDefined();
  });

  it('renders -- placeholders when all fields are null', () => {
    render(
      <EdgeCard
        ticker="MSFT"
        data={{
          expected_30d_edge: null,
          cvar_95: null,
          risk_budget_ratio: null,
          edge_summary: null,
        }}
      />,
    );

    // Should show N/A badge
    expect(screen.getByText('N/A')).toBeDefined();
    // Should show -- for missing fields
    const dashes = screen.getAllByText('--');
    expect(dashes.length).toBeGreaterThan(0);
  });

  it('shows red color and DESTRUCTIVE badge for negative edge', () => {
    render(
      <EdgeCard
        ticker="GOOG"
        data={{
          expected_30d_edge: -5.2,
          cvar_95: 0.10,
          risk_budget_ratio: 0.3,
          edge_summary: 'Bearish signals dominate.',
        }}
      />,
    );

    // Negative edge value present (appears twice: badge + value) — use getAllByText
    const negatives = screen.getAllByText('-5.20%');
    expect(negatives.length).toBeGreaterThan(0);
  });

  it('shows red full-budget badge when risk budget ratio >= 0.9', () => {
    render(
      <EdgeCard
        ticker="TSLA"
        data={{
          expected_30d_edge: 2.0,
          cvar_95: 0.05,
          risk_budget_ratio: 0.95,
          edge_summary: 'High utilization.',
        }}
      />,
    );

    // 95% appears twice (label + value)
    const ninetyFive = screen.getAllByText('95.00%');
    expect(ninetyFive.length).toBeGreaterThan(0);
    // Badge text "Full" is shown
    expect(screen.getByText('Full')).toBeDefined();
  });

  it('shows green OK badge when risk budget ratio is low', () => {
    render(
      <EdgeCard
        ticker="NVDA"
        data={{
          expected_30d_edge: 1.0,
          cvar_95: 0.05,
          risk_budget_ratio: 0.3,
          edge_summary: 'Healthy budget remaining.',
        }}
      />,
    );

    expect(screen.getByText('OK')).toBeDefined();
  });
});

// ---------- pure helper characterization (R20-S9) ----------

describe('formatPct', () => {
  it('returns -- for null / undefined', () => {
    expect(formatPct(null)).toBe('--');
    expect(formatPct(undefined)).toBe('--');
  });

  it('adds + sign for positive values', () => {
    expect(formatPct(7.5)).toBe('+7.50%');
    expect(formatPct(0.1)).toBe('+0.10%');
  });

  it('does not add + for zero or negative', () => {
    expect(formatPct(0)).toBe('0.00%');
    expect(formatPct(-3.2)).toBe('-3.20%');
  });

  it('respects custom digits', () => {
    expect(formatPct(1.2345, 1)).toBe('+1.2%');
    // note: toFixed(3) on 1.2345 yields "1.234" due to IEEE-754 representation
    expect(formatPct(1.2345, 3)).toBe('+1.234%');
  });
});

describe('formatRatio', () => {
  it('returns -- for null / undefined', () => {
    expect(formatRatio(null)).toBe('--');
    expect(formatRatio(undefined)).toBe('--');
  });

  it('multiplies by 100 (ratio → percent)', () => {
    expect(formatRatio(0.08)).toBe('8.00%');
    expect(formatRatio(1)).toBe('100.00%');
  });

  it('does NOT add + sign even for positive (unlike formatPct)', () => {
    expect(formatRatio(0.5)).toBe('50.00%');
  });

  it('respects custom digits', () => {
    expect(formatRatio(0.123456, 1)).toBe('12.3%');
  });
});

describe('edgeColor', () => {
  it('returns muted for null / undefined', () => {
    expect(edgeColor(null)).toBe('text-muted-foreground');
    expect(edgeColor(undefined)).toBe('text-muted-foreground');
  });

  it('strong green for edge > 2', () => {
    expect(edgeColor(3)).toBe('text-green-500');
    expect(edgeColor(2.01)).toBe('text-green-500');
  });

  it('light green for 0 < edge <= 2', () => {
    expect(edgeColor(1)).toBe('text-green-400');
    expect(edgeColor(0.01)).toBe('text-green-400');
  });

  it('light red for -2 < edge <= 0', () => {
    expect(edgeColor(-1)).toBe('text-red-400');
    expect(edgeColor(0)).toBe('text-red-400');
    // -2 is NOT > -2, so it falls to strong red
  });

  it('strong red for edge <= -2', () => {
    expect(edgeColor(-2)).toBe('text-red-500');
    expect(edgeColor(-3)).toBe('text-red-500');
  });
});

describe('riskBudgetVariant', () => {
  it('outline for null / undefined', () => {
    expect(riskBudgetVariant(null)).toBe('outline');
    expect(riskBudgetVariant(undefined)).toBe('outline');
  });

  it('destructive for ratio >= 0.9 (budget nearly exhausted)', () => {
    expect(riskBudgetVariant(0.9)).toBe('destructive');
    expect(riskBudgetVariant(0.95)).toBe('destructive');
    expect(riskBudgetVariant(1)).toBe('destructive');
  });

  it('warning for 0.7 <= ratio < 0.9', () => {
    expect(riskBudgetVariant(0.7)).toBe('warning');
    expect(riskBudgetVariant(0.85)).toBe('warning');
  });

  it('success for ratio < 0.7 (healthy budget)', () => {
    expect(riskBudgetVariant(0)).toBe('success');
    expect(riskBudgetVariant(0.5)).toBe('success');
    expect(riskBudgetVariant(0.69)).toBe('success');
  });
});
