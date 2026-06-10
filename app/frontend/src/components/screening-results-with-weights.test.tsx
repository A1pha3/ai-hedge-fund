/**
 * ScreeningResultsWithWeights 容器测试。
 *
 * 通过 `api` prop 注入 mock (避免模块 mock), 验证:
 *   - 挂载 → 用初始权重调用 api.apply → 渲染结果
 *   - api 失败 → error 透传到 CustomWeightsPanel + 结果清空
 *   - 调整权重 Apply → 用新权重重新调用 api.apply → 结果更新
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ScreeningResultsWithWeights } from './screening-results-with-weights';
import type { ScreeningResponse } from '@/services/custom-weights-api';

function mockApi(initialResp: ScreeningResponse, reweightedResp?: ScreeningResponse) {
  const apply = vi.fn();
  apply.mockResolvedValueOnce(initialResp);
  if (reweightedResp) apply.mockResolvedValueOnce(reweightedResp);
  return { apply };
}

const INITIAL: ScreeningResponse = {
  trade_date: '20260610',
  recommendations: [
    { ticker: '300724', name: '捷佳伟创', score_b: 80.0, decision: 'bullish' },
  ],
  execution_time_seconds: 0.5,
  layer_a_count: 1,
  total_scored: 100,
  high_pool_count: 1,
  top_n: 1,
  meta: {},
};

describe('ScreeningResultsWithWeights', () => {
  it('fetches with initial (equal) weights on mount and renders results', async () => {
    const api = mockApi(INITIAL);

    render(<ScreeningResultsWithWeights api={api} />);

    // Initial weights = equal 0.25 each
    await waitFor(() => {
      expect(api.apply).toHaveBeenCalledWith({
        trend: 0.25,
        mean_reversion: 0.25,
        fundamental: 0.25,
        event_sentiment: 0.25,
      });
    });

    expect(await screen.findByTestId('screening-result-row-300724')).toBeDefined();
    expect(screen.getByTestId('score-300724').textContent).toBe('80.0');
    expect(api.apply).toHaveBeenCalledTimes(1);
  });

  it('surfaces api error into the weights panel + clears results', async () => {
    const apply = vi.fn().mockRejectedValueOnce(new Error('HTTP 404: 未找到报告'));
    const api = { apply };

    render(<ScreeningResultsWithWeights api={api} />);

    expect(await screen.findByTestId('weight-error')).toBeDefined();
    expect(screen.getByTestId('weight-error').textContent).toContain('HTTP 404');
    // Empty results
    expect(screen.getByTestId('screening-results-empty')).toBeDefined();
  });

  it('re-fetches with new weights when user adjusts and applies', async () => {
    const REWEIGHTED: ScreeningResponse = {
      ...INITIAL,
      recommendations: [
        { ticker: '000001', name: '平安银行', score_b: 92.0, decision: 'bullish' },
      ],
    };
    const api = mockApi(INITIAL, REWEIGHTED);

    render(<ScreeningResultsWithWeights api={api} />);

    // Wait for initial load
    await screen.findByTestId('screening-result-row-300724');

    // Adjust trend 0.25 → 0.40, fundamental 0.25 → 0.10 (keep sum 1.0)
    fireEvent.change(screen.getByTestId('weight-trend'), { target: { value: '0.40' } });
    fireEvent.change(screen.getByTestId('weight-fundamental'), { target: { value: '0.10' } });
    fireEvent.click(screen.getByTestId('weight-apply'));

    // Second call with the new weights
    await waitFor(() => {
      expect(api.apply).toHaveBeenNthCalledWith(2, {
        trend: 0.4,
        mean_reversion: 0.25,
        fundamental: 0.1,
        event_sentiment: 0.25,
      });
    });

    // Re-ranked result now shows the new top ticker
    await screen.findByTestId('screening-result-row-000001');
    expect(screen.getByTestId('score-000001').textContent).toBe('92.0');
  });
});
