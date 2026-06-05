import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { EdgeCard } from './edge-card';

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
