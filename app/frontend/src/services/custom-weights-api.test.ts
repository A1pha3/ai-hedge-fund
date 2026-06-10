/**
 * P2-5: custom-weights-api 服务测试。
 *
 * 直接 mock globalThis.fetch (authFetch 内部调用 fetch), 验证:
 *   - apply() POST 正确 body (4 权重 + top_n + trade_date) + 解析 ScreeningResponse
 *   - 非 2xx 响应抛错并透传后端 detail (422 权重和 / 404 无报告)
 *   - sumWeights() 辅助函数算术正确
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { customWeightsApi, sumWeights } from './custom-weights-api';

function mockFetch(response: Response) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);
}

function jsonRes(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

const RESPONSE = {
  trade_date: '20260610',
  recommendations: [
    { ticker: '300724', score_b: 88.2 },
    { ticker: '000001', score_b: 81.0 },
  ],
  market_state: null,
  tracking_summary: null,
  consecutive_recommendation: null,
  industry_rotation: null,
  execution_time_seconds: 1.23,
  batch_data_fetcher: null,
  signal_decay_summary: null,
  sector_concentration_warnings: null,
  layer_a_count: 50,
  total_scored: 4800,
  high_pool_count: 12,
  top_n: 20,
  meta: {},
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('sumWeights', () => {
  it('sums the four strategy weights', () => {
    expect(
      sumWeights({ trend: 0.4, mean_reversion: 0.2, fundamental: 0.3, event_sentiment: 0.1 }),
    ).toBeCloseTo(1.0, 9);
  });
});

describe('customWeightsApi.apply', () => {
  it('POSTs to /api/screening/custom-weights with the four weights + top_n + trade_date', async () => {
    const fetchSpy = mockFetch(jsonRes(RESPONSE));

    const result = await customWeightsApi.apply({
      trend: 0.4,
      mean_reversion: 0.2,
      fundamental: 0.3,
      event_sentiment: 0.1,
      top_n: 20,
      trade_date: '20260610',
    });

    expect(result.trade_date).toBe('20260610');
    expect(result.recommendations[0].ticker).toBe('300724');
    expect(result.top_n).toBe(20);

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toContain('/api/screening/custom-weights');
    expect(init?.method).toBe('POST');
    const body = JSON.parse((init?.body as string) || '{}');
    expect(body.trend).toBe(0.4);
    expect(body.fundamental).toBe(0.3);
    expect(body.top_n).toBe(20);
    expect(body.trade_date).toBe('20260610');
  });

  it('throws on 422 (weight sum != 1.0) and surfaces backend detail', async () => {
    mockFetch(
      jsonRes({ detail: '权重之和必须为 1.0, 当前: 0.900000000' }, { status: 422 }),
    );

    await expect(
      customWeightsApi.apply({
        trend: 0.4,
        mean_reversion: 0.2,
        fundamental: 0.2,
        event_sentiment: 0.1,
      }),
    ).rejects.toThrow(/HTTP 422.*权重之和/);
  });

  it('throws on 404 (no screening report) with status', async () => {
    mockFetch(new Response('not found', { status: 404 }));

    await expect(
      customWeightsApi.apply({
        trend: 0.25,
        mean_reversion: 0.25,
        fundamental: 0.25,
        event_sentiment: 0.25,
      }),
    ).rejects.toThrow(/HTTP 404/);
  });
});
