import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { RiskMonitorPanel } from './risk-monitor-panel';
import type { RiskMetrics } from '@/contexts/node-context';
import type { RiskSnapshot } from '@/services/risk-snapshot-api';

// ---------- Fixtures ----------

const BASE_RISK_METRICS: RiskMetrics = {
  hhi: 0.18,
  short_ratio: 0.12,
  industry_exposures: [
    { ticker: 'AAPL', weight: 0.25, long_value: 25000, short_value: 0, net_value: 25000 },
    { ticker: 'MSFT', weight: 0.20, long_value: 20000, short_value: 0, net_value: 20000 },
    { ticker: 'NVDA', weight: -0.10, long_value: 0, short_value: 10000, net_value: -10000 },
  ],
  cvar_95: 0.08,
  position_count: 3,
  max_single_position_weight: 0.25,
  total_nav: 100000,
  total_long: 45000,
  total_short: 10000,
};

// ---------- Tests ----------

describe('RiskMonitorPanel — P1 1.5', () => {
  it('renders the empty state when riskMetrics is null', () => {
    render(<RiskMonitorPanel riskMetrics={null} />);

    expect(screen.getByTestId('risk-monitor-panel-empty')).toBeDefined();
    expect(screen.getByText(/Run an analysis to see portfolio risk metrics/i)).toBeDefined();
  });

  it('renders HHI gauge, CVaR card, and short ratio with correct severity badges', () => {
    render(<RiskMonitorPanel riskMetrics={BASE_RISK_METRICS} />);

    // Panel is rendered
    expect(screen.getByTestId('risk-monitor-panel')).toBeDefined();

    // HHI — 0.18 is "Moderate" (0.15-0.25 range)
    expect(screen.getByTestId('hhi-value').textContent).toBe('0.180');
    expect(screen.getByTestId('hhi-badge').textContent).toMatch(/Moderate/i);

    // CVaR — 0.08 is "Moderate" (0.05-0.12 range)
    expect(screen.getByTestId('cvar-value').textContent).toBe('8.0%');
    expect(screen.getByTestId('cvar-badge').textContent).toMatch(/Moderate/i);

    // Short ratio — 0.12 is "Moderate" (0.1-0.3 range)
    expect(screen.getByTestId('short-ratio-value').textContent).toBe('12.0%');
    expect(screen.getByTestId('short-ratio-badge').textContent).toMatch(/Moderate/i);

    // Position count
    expect(screen.getByText('3 positions')).toBeDefined();
  });

  it('renders exposure bars for each position with correct colors', () => {
    render(<RiskMonitorPanel riskMetrics={BASE_RISK_METRICS} />);

    // Exposure bars section exists
    expect(screen.getByTestId('exposure-bars')).toBeDefined();

    // AAPL — long (green)
    const aaplBar = screen.getByTestId('exposure-bar-AAPL');
    expect(aaplBar).toBeDefined();
    expect(screen.getByTestId('exposure-pct-AAPL').textContent).toBe('25.0%');

    // NVDA — short (red)
    const nvdaBar = screen.getByTestId('exposure-bar-NVDA');
    expect(nvdaBar).toBeDefined();
    expect(screen.getByTestId('exposure-pct-NVDA').textContent).toBe('-10.0%');
  });

  it('shows "Diversified" badge when HHI is low and "High" when CVaR is high', () => {
    const lowHhiHighCvar: RiskMetrics = {
      ...BASE_RISK_METRICS,
      hhi: 0.08,
      cvar_95: 0.18,
    };

    render(<RiskMonitorPanel riskMetrics={lowHhiHighCvar} />);

    // HHI < 0.15 → Diversified
    expect(screen.getByTestId('hhi-badge').textContent).toMatch(/Diversified/i);

    // CVaR > 0.12 → High
    expect(screen.getByTestId('cvar-badge').textContent).toMatch(/High/i);
    expect(screen.getByTestId('cvar-value').textContent).toBe('18.0%');
  });

  it('renders NAV summary with total NAV and max position weight', () => {
    render(<RiskMonitorPanel riskMetrics={BASE_RISK_METRICS} />);

    const navSummary = screen.getByTestId('nav-summary');
    expect(navSummary).toBeDefined();

    // Total NAV
    expect(screen.getByTestId('nav-value').textContent).toBe('$100.0K');

    // Max position weight
    expect(screen.getByTestId('max-position-weight').textContent).toBe('25.0%');
  });
});

// ---------- P1-6: Live Risk Snapshot fixtures & tests ----------

const BASE_RISK_SNAPSHOT: RiskSnapshot = {
  timestamp: '2026-06-10T10:00:00',
  portfolio_value: 100000,
  var_95: 3200,
  var_99: 5800,
  cvar_95: 4100,
  cvar_99: 7200,
  max_drawdown: 0.14,
  current_drawdown: 0.03,
  drawdown_warning: false,
  industry_concentration: { '信息技术': 0.28, '金融': 0.22, '消费': 0.20 },
  concentration_warning: false,
  single_position_max: 0.18,
  position_count: 5,
  beta_adjusted: 1.12,
};

describe('RiskMonitorPanel — P1-6 Live Risk Snapshot', () => {
  it('renders live-only mode when riskMetrics is null but riskSnapshot is present', () => {
    render(<RiskMonitorPanel riskMetrics={null} riskSnapshot={BASE_RISK_SNAPSHOT} />);

    expect(screen.getByTestId('risk-monitor-panel-live')).toBeDefined();
    expect(screen.getByTestId('live-risk-snapshot')).toBeDefined();
    // VaR cards
    expect(screen.getByTestId('var95-value').textContent).toBe('$3.2K');
    expect(screen.getByTestId('var99-value').textContent).toBe('$5.8K');
    expect(screen.getByTestId('cvar99-value').textContent).toBe('$7.2K');
    // Beta
    expect(screen.getByTestId('beta-value').textContent).toBe('1.12');
  });

  it('renders VaR / drawdown / industry concentration in augmented mode', () => {
    render(<RiskMonitorPanel riskMetrics={BASE_RISK_METRICS} riskSnapshot={BASE_RISK_SNAPSHOT} />);

    // analysis-time section still present
    expect(screen.getByTestId('risk-monitor-panel')).toBeDefined();
    expect(screen.getByTestId('hhi-value').textContent).toBe('0.180');
    // live section also present
    expect(screen.getByTestId('live-risk-snapshot')).toBeDefined();
    expect(screen.getByTestId('current-drawdown-value').textContent).toBe('3.0%');
    expect(screen.getByTestId('max-drawdown-value').textContent).toBe('14.0%');
    // industry concentration bars (top-weighted first)
    expect(screen.getByTestId('industry-fill-信息技术')).toBeDefined();
    expect(screen.queryByTestId('concentration-warning-badge')).toBeNull();
  });

  it('shows drawdown alert badge and red fill when drawdown_warning is true', () => {
    const warning: RiskSnapshot = { ...BASE_RISK_SNAPSHOT, current_drawdown: 0.12, drawdown_warning: true };
    render(<RiskMonitorPanel riskMetrics={null} riskSnapshot={warning} />);

    expect(screen.getByTestId('drawdown-warning-badge')).toBeDefined();
    expect(screen.getByTestId('drawdown-badge').textContent).toMatch(/Warning/i);
  });

  it('shows concentration alert when top industry weight exceeds threshold', () => {
    const concentrated: RiskSnapshot = {
      ...BASE_RISK_SNAPSHOT,
      industry_concentration: { '信息技术': 0.45, '金融': 0.30 },
      concentration_warning: true,
    };
    render(<RiskMonitorPanel riskMetrics={null} riskSnapshot={concentrated} />);

    expect(screen.getByTestId('concentration-warning-badge')).toBeDefined();
    expect(screen.getByTestId('concentration-top-weight').textContent).toMatch(/45\.0%/);
  });

  it('does not render live section when riskSnapshot is absent (backward compat)', () => {
    render(<RiskMonitorPanel riskMetrics={BASE_RISK_METRICS} />);
    expect(screen.queryByTestId('live-risk-snapshot')).toBeNull();
    expect(screen.queryByTestId('risk-monitor-panel-live')).toBeNull();
  });

  it('renders empty state when both riskMetrics and riskSnapshot are null', () => {
    render(<RiskMonitorPanel riskMetrics={null} riskSnapshot={null} />);
    expect(screen.getByTestId('risk-monitor-panel-empty')).toBeDefined();
  });
});
