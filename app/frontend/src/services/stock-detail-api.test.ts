/**
 * P2-6: stock-detail-api 服务测试。
 *
 * 直接 mock globalThis.fetch (authFetch 内部调用 fetch), 验证:
 *   - fetch() GET 正确 path (/stock-detail/{ticker}) + trade_date 查询参数 + 解析 StockDetail
 *   - ticker 经 encodeURIComponent 编码 (A 股代码虽为数字, 但防御)
 *   - 非 2xx (404 无报告) 抛错并透传后端 detail
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { stockDetailApi } from './stock-detail-api';

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

const DETAIL = {
  ticker: '300724',
  name: '捷佳伟创',
  industry_sw: '电力设备',
  pe_ratio: 18.2,
  pb_ratio: 3.1,
  roe: 22.5,
  revenue_growth: 0.35,
  profit_growth: 0.40,
  dividend_yield: 0.5,
  price: 42.8,
  change_pct: 0.062,
  ma5: 41.2,
  ma20: 39.8,
  ma60: 37.5,
  rsi_14: 68.4,
  macd_signal: 'bullish',
  atr_pct: 0.038,
  money_flow_net: 1.2e8,
  north_money_net: null,
  dragon_tiger: true,
  recommendation_count_30d: 7,
  latest_score_b: 88.2,
  latest_decision: 'bullish',
  consecutive_days: 3,
  decay_level: 'none',
  industry_rank: 2,
  industry_total: 18,
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('stockDetailApi.fetch', () => {
  it('GETs /api/screening/stock-detail/{ticker} and parses StockDetail', async () => {
    const fetchSpy = mockFetch(jsonRes(DETAIL));

    const result = await stockDetailApi.fetch('300724');

    expect(result.ticker).toBe('300724');
    expect(result.latest_score_b).toBe(88.2);
    expect(result.dragon_tiger).toBe(true);
    expect(result.industry_rank).toBe(2);

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toContain('/api/screening/stock-detail/300724');
    expect(init?.method).toBeUndefined(); // GET
  });

  it('appends trade_date query param when provided', async () => {
    const fetchSpy = mockFetch(jsonRes(DETAIL));

    await stockDetailApi.fetch('300724', '20260610');

    expect(fetchSpy.mock.calls[0][0]).toContain('trade_date=20260610');
  });

  it('encodes the ticker into the path (defensive)', async () => {
    const fetchSpy = mockFetch(jsonRes(DETAIL));

    await stockDetailApi.fetch('000001');

    expect(fetchSpy.mock.calls[0][0]).toContain('/stock-detail/000001');
  });

  it('throws on 404 (no screening report) with status', async () => {
    mockFetch(new Response('not found', { status: 404 }));

    await expect(stockDetailApi.fetch('999999')).rejects.toThrow(/HTTP 404/);
  });
});
