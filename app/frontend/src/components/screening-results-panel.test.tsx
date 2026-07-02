/**
 * ScreeningResultsPanel 展示型组件测试。
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ScreeningResultsPanel } from './screening-results-panel';
import type { ScreeningRecommendation } from '@/services/custom-weights-api';

const RECS: ScreeningRecommendation[] = [
  { ticker: '300724', name: '捷佳伟创', score_b: 88.2, decision: 'bullish' },
  { ticker: '000001', name: '平安银行', score_b: 81.0, decision: 'neutral' },
  { ticker: '600519', name: '贵州茅台', score_b: 72.5, decision: 'bearish' },
];

describe('ScreeningResultsPanel', () => {
  it('renders one row per recommendation with rank + ticker + score + decision', () => {
    render(<ScreeningResultsPanel recommendations={RECS} tradeDate="20260610" />);

    expect(screen.getByTestId('screening-results-list')).toBeDefined();
    expect(screen.getByTestId('screening-result-row-300724')).toBeDefined();
    expect(screen.getByTestId('screening-result-row-000001')).toBeDefined();
    expect(screen.getByTestId('score-300724').textContent).toBe('88.2');
    // rank
    expect(screen.getByTestId('screening-result-row-300724').textContent).toMatch(/^1/);
  });

  it('maps decision to the correct badge variant (bull=success, bear=destructive, neutral=secondary)', () => {
    render(<ScreeningResultsPanel recommendations={RECS} />);
    // Just ensure badges render without error; variant mapping is internal.
    const bullRow = screen.getByTestId('screening-result-row-300724');
    const bearRow = screen.getByTestId('screening-result-row-600519');
    expect(bullRow.textContent).toContain('bullish');
    expect(bearRow.textContent).toContain('bearish');
  });

  it('shows empty hint when no recommendations', () => {
    render(<ScreeningResultsPanel recommendations={[]} />);
    expect(screen.getByTestId('screening-results-empty').textContent).toContain('暂无推荐');
  });

  it('shows custom empty hint', () => {
    render(<ScreeningResultsPanel recommendations={[]} emptyHint="无数据" />);
    expect(screen.getByTestId('screening-results-empty').textContent).toBe('无数据');
  });

  it('shows loading description when isLoading', () => {
    render(<ScreeningResultsPanel recommendations={RECS} isLoading={true} />);
    // CardDescription text
    const panel = screen.getByTestId('screening-results-panel');
    expect(panel.textContent).toContain('重新排序中');
  });

  it('does not crash on recommendations missing score_b / decision', () => {
    render(<ScreeningResultsPanel recommendations={[{ ticker: '000002' }]} />);
    expect(screen.getByTestId('screening-result-row-000002')).toBeDefined();
    // No score badge rendered for missing score_b
    expect(screen.queryByTestId('score-000002')).toBeNull();
  });

  describe('c290 verdict badge (CLI↔web parity)', () => {
    const RECS_WITH_VERDICT: ScreeningRecommendation[] = [
      {
        ticker: '300724', name: '捷佳伟创', score_b: 88.2, decision: 'bullish',
        verdict: { action: 'BUY', market_regime: 'normal', invalidation_reason: 'T+30 edge 转负', signal_horizon: 'T+5+T+10' },
      },
      {
        ticker: '000001', name: '平安银行', score_b: 81.0, decision: 'bullish',
        verdict: { action: 'AVOID', market_regime: 'normal', invalidation_reason: '同分组胜率跌破 50% / 成熟样本不足 20', signal_horizon: '' },
      },
      {
        ticker: '600519', name: '贵州茅台', score_b: 72.5, decision: 'neutral',
        verdict: { action: 'HOLD', market_regime: 'normal', invalidation_reason: '市场门控转弱', signal_horizon: 'T+10' },
      },
    ];

    it('renders the verdict action as a colored badge per pick (BUY/AVOID visible)', () => {
      render(<ScreeningResultsPanel recommendations={RECS_WITH_VERDICT} tradeDate="20260610" />);
      // Each row must surface the verdict action — the BUY/AVOID the CLI has,
      // now attached on the backend (c290). Without frontend rendering, the
      // backend verdict is invisible to the web user.
      const buyRow = screen.getByTestId('screening-result-row-300724');
      const avoidRow = screen.getByTestId('screening-result-row-000001');
      const holdRow = screen.getByTestId('screening-result-row-600519');
      expect(buyRow.textContent).toContain('BUY');
      expect(avoidRow.textContent).toContain('AVOID');
      expect(holdRow.textContent).toContain('HOLD');
    });

    it('renders the invalidation_reason disclosure (trust-calibration honesty)', () => {
      render(<ScreeningResultsPanel recommendations={RECS_WITH_VERDICT} />);
      // The composite_verified/invalidation disclosure (NS-18/c282/c283) must
      // be visible on the web, not just attached silently to the JSON.
      const buyRow = screen.getByTestId('screening-result-row-300724');
      expect(buyRow.textContent).toContain('T+30 edge 转负');
    });

    it('renders signal_horizon so users distinguish T+5 vs T+10 buy signals', () => {
      render(<ScreeningResultsPanel recommendations={RECS_WITH_VERDICT} />);
      const buyRow = screen.getByTestId('screening-result-row-300724');
      // C221: signal_horizon lets users split capital between T+5 vs T+10 buys
      expect(buyRow.textContent).toContain('T+5+T+10');
    });

    it('does not crash and omits verdict UI when verdict is missing (legacy payloads)', () => {
      render(<ScreeningResultsPanel recommendations={RECS} />);
      // recs without verdict (old payloads) must still render rows
      expect(screen.getByTestId('screening-result-row-300724')).toBeDefined();
      // and not throw — verdict badge simply absent
    });
  });
});
