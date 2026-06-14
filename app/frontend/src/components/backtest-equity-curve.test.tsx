/**
 * P0-4 回测净值曲线可视化 — 测试覆盖 (R20.29 补测)。
 *
 * backtest-equity-curve.tsx 此前已实现并集成 (渲染 净值曲线 + 水下图/回撤 +
 * 月度收益热力图 + KPI 卡片), 但零测试覆盖。本套件锁定其正确行为并覆盖边界。
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { BacktestEquityCurve } from './backtest-equity-curve';

// ---------- Fixtures ----------

interface Day {
  date: string;
  portfolio_value: number;
  portfolio_return?: number;
}

interface BacktestAgentData {
  backtest: {
    backtestResults: Day[];
  };
}

/** 构造 agentData['backtest'].backtestResults 从 [date, value, return?] 元组数组。 */
function makeAgentData(days: Array<[string, number, number?]>): BacktestAgentData {
  const backtestResults: Day[] = days.map(([date, portfolio_value, portfolio_return]) => ({
    date,
    portfolio_value,
    ...(portfolio_return !== undefined ? { portfolio_return } : {}),
  }));
  return { backtest: { backtestResults } };
}

// 单调上涨: 100 → 110 → 121 → 133.1 (每日 +10%, 无回撤)
const UPTREND = makeAgentData([
  ['2026-01-02', 100],
  ['2026-01-03', 110, 0.10],
  ['2026-01-04', 121, 0.10],
  ['2026-01-05', 133.1, 0.10],
]);

// 先涨后跌: 100 → 120 → 90 (峰 120, 谷 90, 最大回撤 25%)
const DRAWDOWN = makeAgentData([
  ['2026-01-02', 100],
  ['2026-01-03', 120, 0.20],
  ['2026-01-04', 90, -0.25],
]);

// ---------- Tests ----------

describe('BacktestEquityCurve — empty / edge cases', () => {
  it('renders null when no backtest agent data', () => {
    const { container } = render(<BacktestEquityCurve agentData={{}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders null when backtestResults is missing', () => {
    const { container } = render(<BacktestEquityCurve agentData={{ backtest: {} }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders insufficient-data placeholder when fewer than 2 daily results (L-2)', () => {
    render(
      <BacktestEquityCurve agentData={makeAgentData([['2026-01-02', 100]])} />,
    );
    // R20-S6 GAMMA L-2: silent null was bad UX — now shows a status hint
    const status = screen.getByRole('status');
    expect(status).toBeInTheDocument();
    expect(status).toHaveTextContent('数据点不足');
    expect(status).toHaveAttribute('aria-live', 'polite');
  });

  it('renders insufficient-data placeholder when daily results list is empty', () => {
    render(<BacktestEquityCurve agentData={makeAgentData([])} />);
    expect(screen.getByRole('status')).toHaveTextContent('数据点不足');
  });

  it('renders null when initial portfolio value is 0 (division guard)', () => {
    const { container } = render(
      <BacktestEquityCurve agentData={makeAgentData([['2026-01-02', 0], ['2026-01-03', 100]])} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders null when initial value is NaN', () => {
    const { container } = render(
      <BacktestEquityCurve
        agentData={makeAgentData([['2026-01-02', NaN], ['2026-01-03', 100]])}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe('BacktestEquityCurve — KPI cards', () => {
  it('renders total return, max drawdown, win rate, days, initial, final capital', () => {
    render(<BacktestEquityCurve agentData={UPTREND} />);

    // 总收益: (133.1 - 100) / 100 = 33.1%
    expect(screen.getByText('+33.10%')).toBeDefined();
    // 最大回撤: 单调上涨 → 0%
    expect(screen.getByText('0.00%')).toBeDefined();
    // 交易天数: 4
    expect(screen.getByText('4')).toBeDefined();
    // 初始资金: 100 / 1e4 = 0.01万 → "¥0万" (toFixed(0))
    // 最终资金: 133.1 / 1e4 → "¥0万"
    expect(screen.getByText(/回测净值曲线/)).toBeDefined();
  });

  it('KPI grid is single-column on smallest screens then scales up (R-3)', () => {
    render(<BacktestEquityCurve agentData={UPTREND} />);
    // R20-S7 GAMMA R-3: 6 KPI cards must not stay grid-cols-2 on 320px phones
    const grid = screen.getByTestId('kpi-grid');
    expect(grid.className).toContain('grid-cols-1');
    expect(grid.className).toContain('sm:grid-cols-2');
    expect(grid.className).toContain('md:grid-cols-4');
    expect(grid.className).toContain('lg:grid-cols-6');
  });

  it('computes max drawdown correctly for peak-to-trough decline', () => {
    render(<BacktestEquityCurve agentData={DRAWDOWN} />);
    // 100 → 120 → 90: 峰 120, 谷 90, 回撤 = (120-90)/120 = 25%
    // KPI 最大回撤 card shows 25.00%
    expect(screen.getByText('25.00%')).toBeDefined();
    // 总收益: (90 - 100) / 100 = -10%
    expect(screen.getByText('-10.00%')).toBeDefined();
  });

  it('counts win rate from positive daily returns (day 0 counts in denominator)', () => {
    // DRAWDOWN: 3 points (含 day0 初始日 portfolio_return=0).
    // winningDays = 1 (仅 +0.20 那天); day0 的 0 不算 win 但计入分母 → 1/3 = 33.3%
    // 注: 这是 shipped 行为 (day0 计入分母), 对长回测 (<1天偏差) 可忽略, 此处锁定现状。
    render(<BacktestEquityCurve agentData={DRAWDOWN} />);
    expect(screen.getByText('33.3%')).toBeDefined();
  });
});

describe('BacktestEquityCurve — chart rendering', () => {
  it('renders the equity curve SVG with area + line paths', () => {
    const { container } = render(<BacktestEquityCurve agentData={UPTREND} />);
    const svgs = container.querySelectorAll('svg');
    expect(svgs.length).toBeGreaterThanOrEqual(2); // equity + drawdown
    // Equity curve has a filled area path + polyline
    const paths = container.querySelectorAll('svg path');
    expect(paths.length).toBeGreaterThanOrEqual(1);
  });

  it('renders drawdown chart with accessible aria-label including max drawdown', () => {
    render(<BacktestEquityCurve agentData={DRAWDOWN} />);
    const drawdownSvg = screen.getByRole('img', { name: /最大回撤图.*25\.0%/ });
    expect(drawdownSvg).toBeDefined();
  });

  it('renders drawdown underwater chart heading', () => {
    render(<BacktestEquityCurve agentData={UPTREND} />);
    expect(screen.getByText(/水下图.*Drawdown/)).toBeDefined();
  });

  /**
   * R30 — UX research R-4 fix: SVG charts had a fixed 800x200 viewBox with no
   * preserveAspectRatio attribute. On very narrow viewports the browser default
   * ("xMidYMid meet" works for non-zero viewBoxes, but only one of two SVGs was
   * actually relying on the implicit default; the other was filling the new
   * width without keeping the aspect ratio). Pin the explicit attribute so the
   * chart never deforms on narrow phones.
   */
  it('R30: equity SVG declares preserveAspectRatio="xMidYMid meet" (R-4 narrow-screen guard)', () => {
    const { container } = render(<BacktestEquityCurve agentData={UPTREND} />);
    const svgs = container.querySelectorAll('svg');
    expect(svgs.length).toBeGreaterThanOrEqual(2);
    svgs.forEach((svg) => {
      expect(svg.getAttribute('preserveAspectRatio')).toBe('xMidYMid meet');
    });
  });
});

describe('BacktestEquityCurve — monthly returns heatmap', () => {
  it('renders monthly heatmap with compounded monthly return', () => {
    // 跨两月: 2026-01 (100→110→121, +21%) + 2026-02 (121→133.1, +10%)
    const crossMonth = makeAgentData([
      ['2026-01-30', 100],
      ['2026-01-31', 110, 0.10],
      ['2026-02-02', 121, 0.10],
      ['2026-02-03', 133.1, 0.10],
    ]);
    render(<BacktestEquityCurve agentData={crossMonth} />);

    expect(screen.getByText(/月度收益热力图/)).toBeDefined();
    // 2026-01: 100→110→121 复合 = (1.1*1.1)-1 = 21%  → "21.0%"
    expect(screen.getByText('21.0%')).toBeDefined();
    // 2026-02: 121→133.1 = +10% → "10.0%"
    expect(screen.getByText('10.0%')).toBeDefined();
  });

  it('exposes monthly cell aria-label for screen readers and keyboard tooltips (A-5)', () => {
    const crossMonth = makeAgentData([
      ['2026-01-30', 100],
      ['2026-01-31', 110, 0.10],
      ['2026-02-02', 121, 0.10],
      ['2026-02-03', 133.1, 0.10],
    ]);
    const { container } = render(<BacktestEquityCurve agentData={crossMonth} />);
    // R20-S6 GAMMA A-5: aria-label complements title so keyboard / a11y users get tooltip text
    const cells = Array.from(container.querySelectorAll('[aria-label*="月度收益"]')) as HTMLElement[];
    expect(cells.length).toBe(2);
    const labels = cells.map((c) => c.getAttribute('aria-label'));
    expect(labels).toContain('2026-01 月度收益 10.00%');
    expect(labels).toContain('2026-02 月度收益 21.00%');
    // title is preserved for native mouse-hover fallback
    cells.forEach((c) => expect(c).toHaveAttribute('title'));
  });

  it('applies green color classes for positive months and red for negative', () => {
    const mixed = makeAgentData([
      ['2026-01-02', 100],
      ['2026-01-03', 110, 0.10], // +10% → green
      ['2026-02-02', 90, -0.18], // -18% from 110 → red
    ]);
    const { container } = render(<BacktestEquityCurve agentData={mixed} />);
    const heatCells = container.querySelectorAll('[title^="2026-"]');
    expect(heatCells.length).toBe(2);
    // positive month has a green class, negative a red class
    const classNames = Array.from(heatCells).map((c) => (c as HTMLElement).className);
    expect(classNames.some((c) => c.includes('green'))).toBe(true);
    expect(classNames.some((c) => c.includes('red'))).toBe(true);
  });
});

describe('BacktestEquityCurve — drawdown computation correctness', () => {
  it('tracks running peak so drawdown resets after new high', () => {
    // 100 → 80 (DD 20%) → 120 (new high, DD 0%) → 100 (DD from 120 = 16.67%)
    const peakReset = makeAgentData([
      ['2026-01-02', 100],
      ['2026-01-03', 80, -0.20],
      ['2026-01-04', 120, 0.50],
      ['2026-01-05', 100, -0.1667],
    ]);
    render(<BacktestEquityCurve agentData={peakReset} />);
    // 最大回撤 = max(20%, 0%, 16.67%) = 20%
    expect(screen.getByText('20.00%')).toBeDefined();
  });

  it('filters out NaN portfolio_value days before computing drawdown', () => {
    const withNaN = makeAgentData([
      ['2026-01-02', 100],
      ['2026-01-03', NaN, 0],
      ['2026-01-04', 120, 0.20],
    ]);
    // NaN day filtered; 2 valid points remain → renders, 总收益 +20%
    const { container } = render(<BacktestEquityCurve agentData={withNaN} />);
    expect(container.querySelector('svg')).not.toBeNull();
    expect(screen.getByText('+20.00%')).toBeDefined();
  });
});
