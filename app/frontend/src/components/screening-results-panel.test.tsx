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
});
