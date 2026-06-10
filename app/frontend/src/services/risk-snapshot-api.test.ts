/**
 * P1-6: risk-snapshot-api 服务测试。
 *
 * 直接 mock globalThis.fetch (authFetch 内部调用 fetch), 验证:
 *   - compute() POST 正确 body + 解析 RiskSnapshot
 *   - fetchEmpty() GET 带 lookback_days 查询参数
 *   - fetchThresholds() GET 阈值端点
 *   - 非 2xx 响应抛错 (带状态码)
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { riskSnapshotApi } from './risk-snapshot-api';

// authFetch 读 getStoredToken(); 测试环境无 token, 走纯 fetch 路径。
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

const SNAPSHOT = {
  timestamp: '2026-06-10T10:00:00',
  portfolio_value: 100000,
  var_95: 3200,
  var_99: 5800,
  cvar_95: 4100,
  cvar_99: 7200,
  max_drawdown: 0.14,
  current_drawdown: 0.03,
  drawdown_warning: false,
  industry_concentration: { '信息技术': 0.28 },
  concentration_warning: false,
  single_position_max: 0.18,
  position_count: 5,
  beta_adjusted: 1.12,
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('riskSnapshotApi.compute', () => {
  it('POSTs to /api/portfolio/risk-snapshot with full payload and returns parsed snapshot', async () => {
    const fetchSpy = mockFetch(jsonRes(SNAPSHOT));

    const result = await riskSnapshotApi.compute({
      positions: [{ ticker: 'AAPL', shares: 100, current_price: 150 }],
      lookback_returns: [{ date: '2026-06-09', ticker: 'AAPL', return_pct: 0.01 }],
      initial_portfolio_value: 100000,
      var_horizon_days: 1,
    });

    expect(result.var_95).toBe(3200);
    expect(result.beta_adjusted).toBe(1.12);

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toContain('/api/portfolio/risk-snapshot');
    expect(init?.method).toBe('POST');
    const body = JSON.parse((init?.body as string) || '{}');
    expect(body.positions[0].ticker).toBe('AAPL');
    expect(body.var_horizon_days).toBe(1);
  });

  it('throws on non-2xx response', async () => {
    mockFetch(new Response('bad', { status: 500 }));
    await expect(
      riskSnapshotApi.compute({ positions: [], lookback_returns: [] }),
    ).rejects.toThrow(/HTTP 500/);
  });
});

describe('riskSnapshotApi.fetchEmpty', () => {
  it('GETs with lookback_days query param', async () => {
    const fetchSpy = mockFetch(jsonRes({ ...SNAPSHOT, portfolio_value: 0, position_count: 0 }));

    const result = await riskSnapshotApi.fetchEmpty(90);

    expect(result.position_count).toBe(0);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toContain('lookback_days=90');
    expect(init?.method).toBeUndefined(); // GET
  });

  it('defaults lookback_days to 60', async () => {
    const fetchSpy = mockFetch(jsonRes(SNAPSHOT));
    await riskSnapshotApi.fetchEmpty();
    expect(fetchSpy.mock.calls[0][0]).toContain('lookback_days=60');
  });
});

describe('riskSnapshotApi.fetchThresholds', () => {
  it('returns the three warning thresholds', async () => {
    mockFetch(
      jsonRes({ industry_concentration: 0.25, single_position: 0.12, drawdown: 0.10 }),
    );
    const t = await riskSnapshotApi.fetchThresholds();
    expect(t.industry_concentration).toBe(0.25);
    expect(t.single_position).toBe(0.12);
    expect(t.drawdown).toBe(0.10);
  });
});
