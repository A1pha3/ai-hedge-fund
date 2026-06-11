/**
 * 闭环验证仪表盘 — 集成 P3-1/P3-2/P3-3/P3-4 输出。
 *
 * 让用户在 Web 端一站式看到:
 *   - P3-1: 推荐实际收益闭环 (胜率 / 平均 T+N 收益)
 *   - P3-2: 当前策略权重 vs 校准后权重
 *   - P3-3: 行业 + 个股交叉选择 (强势行业 + 行业最优标的)
 *   - P3-4: 推荐组合 (权重 + 行业分布 + Sharpe)
 *
 * 共享展示面 — 数据由父组件 fetch 传入, 与 macro-dashboard / risk-monitor 一致。
 */
import { useCallback, useEffect, useState } from 'react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Activity, BarChart3, PieChart, Scale } from 'lucide-react';

// ---------------------------------------------------------------------------
// Types (mirroring backend dataclasses)
// ---------------------------------------------------------------------------

export interface VerifyDay {
  date: string;
  tickers: string[];
  top_score: number;
  avg_t1_return: number | null;
  avg_t3_return: number | null;
  avg_t5_return: number | null;
  benchmark_return: number | null;
  excess_return: number | null;
}

export interface VerifySummary {
  lookback_days: number;
  total_days: number;
  total_recommendations: number;
  unique_tickers: number;
  overall_t1_win_rate: number | null;
  overall_t3_win_rate: number | null;
  overall_t5_win_rate: number | null;
  avg_t1_return: number | null;
  avg_t3_return: number | null;
  avg_t5_return: number | null;
  benchmark_avg_t1: number | null;
  excess_return: number | null;
  strategy_attribution: Array<{
    strategy_name: string;
    recommendation_count: number;
    avg_t1_return: number | null;
    win_rate: number | null;
  }>;
}

export interface WeightCalibrationResult {
  lookback_days: number;
  original_weights: Record<string, number>;
  calibrated_weights: Record<string, number>;
  n_factors: number;
  n_observations: number;
  calibration_skipped: boolean;
}

export interface CrossPick {
  industry_name: string;
  industry_rank: number;
  momentum_score: number;
  candidate_count: number;
  top_picks: Array<{
    ticker: string;
    name: string;
    score_b: number;
    decision: string;
  }>;
}

export interface PortfolioSummary {
  n_positions: number;
  total_weight: number;
  industry_breakdown: Record<string, number>;
  concentration_top1: number;
  concentration_top3: number;
  expected_sharpe: number;
  equal_weight_sharpe: number;
  positions: Array<{
    ticker: string;
    name: string;
    industry: string;
    score_b: number;
    weight: number;
  }>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _pct(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${(v * 100).toFixed(digits)}%`;
}

// ---------------------------------------------------------------------------
// Tab: Verify (P3-1)
// ---------------------------------------------------------------------------

function _VerifyTab({ summary }: { summary: VerifySummary | null }) {
  if (!summary) {
    return <p className="text-sm text-muted-foreground">暂无闭环验证数据 — 请先运行 --verify-recommendations</p>;
  }

  return (
    <div className="space-y-3" data-testid="verify-tab">
      <div className="grid grid-cols-3 gap-2 text-sm">
        <div className="rounded bg-muted/30 p-2">
          <div className="text-muted-foreground text-xs">T+1 胜率</div>
          <div className="font-mono font-medium">{_pct(summary.overall_t1_win_rate)}</div>
        </div>
        <div className="rounded bg-muted/30 p-2">
          <div className="text-muted-foreground text-xs">T+1 平均收益</div>
          <div className="font-mono font-medium">{_pct(summary.avg_t1_return, 2)}</div>
        </div>
        <div className="rounded bg-muted/30 p-2">
          <div className="text-muted-foreground text-xs">超额收益</div>
          <div className="font-mono font-medium">{_pct(summary.excess_return, 2)}</div>
        </div>
      </div>

      {summary.strategy_attribution.length > 0 && (
        <div className="text-xs">
          <div className="text-muted-foreground mb-1">策略归因 (T+1):</div>
          {summary.strategy_attribution.map((s) => (
            <div key={s.strategy_name} className="flex justify-between py-0.5">
              <span>{s.strategy_name}</span>
              <span className="font-mono">
                {_pct(s.avg_t1_return, 2)} ({_pct(s.win_rate)} WR)
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="text-xs text-muted-foreground">
        总推荐 {summary.total_recommendations} 标的 / {summary.unique_tickers} 不重复 / 近 {summary.lookback_days} 天
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Weights (P3-2)
// ---------------------------------------------------------------------------

function _WeightsTab({ result }: { result: WeightCalibrationResult | null }) {
  if (!result) {
    return <p className="text-sm text-muted-foreground">暂无权重校准数据 — 请先运行 --calibrate-weights</p>;
  }

  if (result.calibration_skipped) {
    return <p className="text-sm text-muted-foreground">校准跳过 — 需要 ≥5 期因子历史</p>;
  }

  return (
    <div className="space-y-2" data-testid="weights-tab">
      {Object.entries(result.original_weights).map(([strat, orig]) => {
        const cal = result.calibrated_weights[strat] || orig;
        const delta = cal - orig;
        return (
          <div key={strat} className="text-xs">
            <div className="flex justify-between mb-0.5">
              <span className="font-medium">{strat}</span>
              <span className="font-mono">
                {orig.toFixed(2)} → {cal.toFixed(2)}{' '}
                <span className={delta > 0 ? 'text-green-600' : delta < 0 ? 'text-red-500' : 'text-muted-foreground'}>
                  ({delta >= 0 ? '+' : ''}{delta.toFixed(2)})
                </span>
              </span>
            </div>
            {/* Simple bar */}
            <div className="h-1.5 rounded bg-muted/30 overflow-hidden">
              <div
                className="h-full bg-primary"
                style={{ width: `${cal * 100}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Cross Picks (P3-3)
// ---------------------------------------------------------------------------

function _CrossPicksTab({ picks }: { picks: CrossPick[] | null }) {
  if (!picks || picks.length === 0) {
    return <p className="text-sm text-muted-foreground">暂无交叉选择数据 — 请先运行 --cross-picks</p>;
  }

  return (
    <div className="space-y-3" data-testid="cross-picks-tab">
      {picks.slice(0, 5).map((cp) => (
        <div key={cp.industry_name} className="text-xs">
          <div className="flex items-center justify-between mb-0.5">
            <span className="font-medium">
              #{cp.industry_rank} {cp.industry_name}
            </span>
            <Badge variant="outline" className="text-[10px]">
              动量 {cp.momentum_score >= 0 ? '+' : ''}{cp.momentum_score.toFixed(1)}
            </Badge>
          </div>
          {cp.top_picks.length > 0 && (
            <div className="text-muted-foreground">
              {cp.top_picks.slice(0, 2).map((p) => (
                <span key={p.ticker} className="mr-2 font-mono">
                  {p.ticker}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Portfolio (P3-4)
// ---------------------------------------------------------------------------

function _PortfolioTab({ summary }: { summary: PortfolioSummary | null }) {
  if (!summary) {
    return <p className="text-sm text-muted-foreground">暂无组合数据 — 请先运行 --build-portfolio</p>;
  }

  if (summary.n_positions === 0) {
    return <p className="text-sm text-muted-foreground">无推荐数据</p>;
  }

  return (
    <div className="space-y-3" data-testid="portfolio-tab">
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded bg-muted/30 p-2">
          <div className="text-muted-foreground text-xs">持仓数</div>
          <div className="font-mono font-medium">{summary.n_positions}</div>
        </div>
        <div className="rounded bg-muted/30 p-2">
          <div className="text-muted-foreground text-xs">最大单一</div>
          <div className="font-mono font-medium">{_pct(summary.concentration_top1, 1)}</div>
        </div>
      </div>

      {/* Top 3 positions */}
      <div className="text-xs">
        <div className="text-muted-foreground mb-1">Top 持仓:</div>
        {summary.positions.slice(0, 3).map((p) => (
          <div key={p.ticker} className="flex justify-between py-0.5">
            <span className="font-mono">{p.ticker} {p.name}</span>
            <span className="font-mono">{(p.weight * 100).toFixed(1)}%</span>
          </div>
        ))}
      </div>

      {/* Industry breakdown mini-bars */}
      {Object.keys(summary.industry_breakdown).length > 0 && (
        <div className="text-xs">
          <div className="text-muted-foreground mb-1">行业分布:</div>
          {Object.entries(summary.industry_breakdown)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 4)
            .map(([ind, w]) => (
              <div key={ind} className="flex items-center gap-2 py-0.5">
                <span className="w-16 truncate">{ind}</span>
                <div className="flex-1 h-1.5 rounded bg-muted/30 overflow-hidden">
                  <div className="h-full bg-primary" style={{ width: `${w * 100}%` }} />
                </div>
                <span className="font-mono w-12 text-right">{(w * 100).toFixed(1)}%</span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export interface VerifyDashboardProps {
  /** P3-1 推荐闭环验证 */
  verifySummary?: VerifySummary | null;
  /** P3-2 权重校准 */
  weightResult?: WeightCalibrationResult | null;
  /** P3-3 行业+个股交叉选择 */
  crossPicks?: CrossPick[] | null;
  /** P3-4 组合 */
  portfolio?: PortfolioSummary | null;
  /** 是否正在加载。 */
  isLoading?: boolean;
}

export function VerifyDashboard({
  verifySummary = null,
  weightResult = null,
  crossPicks = null,
  portfolio = null,
  isLoading = false,
}: VerifyDashboardProps) {
  if (isLoading) {
    return (
      <Card className="overflow-hidden" data-testid="verify-dashboard">
        <CardHeader className="bg-muted/50 pb-3">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            <CardTitle className="text-base">闭环验证</CardTitle>
          </div>
          <CardDescription>加载中…</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  // No data at all → show empty state
  if (!verifySummary && !weightResult && !crossPicks?.length && !portfolio) {
    return (
      <Card className="overflow-hidden" data-testid="verify-dashboard">
        <CardHeader className="bg-muted/50 pb-3">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            <CardTitle className="text-base">闭环验证</CardTitle>
          </div>
          <CardDescription>暂无数据 — 运行 P3 CLI 命令生成报告</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden" data-testid="verify-dashboard">
      <CardHeader className="bg-muted/50 pb-3">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          <CardTitle className="text-base">闭环验证 (P3)</CardTitle>
        </div>
        <CardDescription>推荐胜率 + 权重校准 + 行业交叉 + 组合</CardDescription>
      </CardHeader>
      <CardContent className="pt-2">
        <Tabs defaultValue="verify" className="w-full">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="verify" className="text-xs">
              <BarChart3 className="mr-1 h-3 w-3" />胜率
            </TabsTrigger>
            <TabsTrigger value="weights" className="text-xs">
              <Scale className="mr-1 h-3 w-3" />权重
            </TabsTrigger>
            <TabsTrigger value="cross" className="text-xs">
              <Activity className="mr-1 h-3 w-3" />交叉
            </TabsTrigger>
            <TabsTrigger value="portfolio" className="text-xs">
              <PieChart className="mr-1 h-3 w-3" />组合
            </TabsTrigger>
          </TabsList>
          <TabsContent value="verify" className="mt-3">
            <_VerifyTab summary={verifySummary ?? null} />
          </TabsContent>
          <TabsContent value="weights" className="mt-3">
            <_WeightsTab result={weightResult ?? null} />
          </TabsContent>
          <TabsContent value="cross" className="mt-3">
            <_CrossPicksTab picks={crossPicks ?? null} />
          </TabsContent>
          <TabsContent value="portfolio" className="mt-3">
            <_PortfolioTab summary={portfolio ?? null} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
