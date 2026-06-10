/**
 * P2-2: 回测参数对比面板 (展示型组件)。
 *
 * 以表格形式展示不同参数组合的回测指标对比:
 *   - 每行 = 一个参数组合 (trial)
 *   - 列 = 参数列 + 标准指标列 (Sharpe / Sortino / 最大回撤 / 胜率 / 总收益)
 *   - 最佳指标值高亮 (每列最优单元格加粗 + 标记 ★)
 *   - 失败 trial 灰色显示 + 错误信息
 *
 * 纯展示组件 — 数据由父组件传入。对齐 stock-detail-card / custom-weights-panel 模式。
 */
import { useState, useMemo } from 'react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ArrowUpDown, Trophy } from 'lucide-react';

import {
  COMPARISON_METRICS,
  METRIC_LABELS,
  formatMetricValue,
  type ParamCompareReport,
  type ParamTrial,
} from '@/services/param-compare-api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** 获取 trial 的参数摘要 (简短显示)。 */
function _paramSummary(params: Record<string, unknown>): string {
  const entries = Object.entries(params);
  if (entries.length === 0) return '(default)';
  return entries.map(([k, v]) => `${k}=${v}`).join(', ');
}

/** 对每个指标列找到最佳 trial (最高值最优, max_drawdown 除外取绝对值最小)。 */
function _findBestTrials(trials: ParamTrial[]): Map<string, number> {
  const best = new Map<string, number>();
  const passing = trials.filter((t) => !t.error);

  for (const metric of COMPARISON_METRICS) {
    let bestIdx = -1;
    let bestVal: number | null = null;

    for (let i = 0; i < passing.length; i++) {
      const v = passing[i].metrics[metric];
      if (v == null || typeof v !== 'number' || !Number.isFinite(v)) continue;

      if (bestVal == null) {
        bestVal = v;
        bestIdx = i;
      } else if (metric === 'max_drawdown') {
        // 最小绝对回撤 = 最佳
        if (Math.abs(v) < Math.abs(bestVal)) {
          bestVal = v;
          bestIdx = i;
        }
      } else {
        if (v > bestVal) {
          bestVal = v;
          bestIdx = i;
        }
      }
    }

    if (bestIdx >= 0) {
      best.set(metric, bestIdx);
    }
  }

  return best;
}

// ---------------------------------------------------------------------------
// Sort state
// ---------------------------------------------------------------------------

type SortDir = 'asc' | 'desc' | null;

function _sortTrials(trials: ParamTrial[], metric: string, dir: SortDir): ParamTrial[] {
  if (!dir) return trials;
  const sorted = [...trials];
  sorted.sort((a, b) => {
    // Failed trials always last
    if (a.error && !b.error) return 1;
    if (!a.error && b.error) return -1;

    const va = a.metrics[metric];
    const vb = b.metrics[metric];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    const na = typeof va === 'number' ? va : 0;
    const nb = typeof vb === 'number' ? vb : 0;
    return dir === 'desc' ? nb - na : na - nb;
  });
  return sorted;
}

// ---------------------------------------------------------------------------
// Props & Component
// ---------------------------------------------------------------------------

export interface ParamComparePanelProps {
  /** 参数对比报告数据。 */
  report: ParamCompareReport | null;
  /** 是否正在加载。 */
  isLoading?: boolean;
}

export function ParamComparePanel({ report, isLoading = false }: ParamComparePanelProps) {
  const [sortMetric, setSortMetric] = useState<string>('sharpe_ratio');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const trials = useMemo(() => {
    if (!report) return [];
    return _sortTrials(report.trials, sortMetric, sortDir);
  }, [report, sortMetric, sortDir]);

  const bestTrials = useMemo(() => {
    if (!report) return new Map<string, number>();
    return _findBestTrials(report.trials);
  }, [report]);

  const handleSort = (metric: string) => {
    if (sortMetric === metric) {
      // Cycle: desc → asc → null → desc
      setSortDir((prev) => (prev === 'desc' ? 'asc' : prev === 'asc' ? null : 'desc'));
    } else {
      setSortMetric(metric);
      setSortDir('desc');
    }
  };

  if (isLoading) {
    return (
      <Card className="overflow-hidden" data-testid="param-compare-panel">
        <CardHeader className="bg-muted/50 pb-3">
          <CardTitle className="text-base">参数对比</CardTitle>
          <CardDescription>加载中…</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (!report || report.trials.length === 0) {
    return (
      <Card className="overflow-hidden" data-testid="param-compare-panel">
        <CardHeader className="bg-muted/50 pb-3">
          <CardTitle className="text-base">参数对比</CardTitle>
          <CardDescription>暂无对比数据 — 请先用 --param-grid 运行参数搜索</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const passing = report.trials.filter((t) => !t.error);
  const failed = report.trials.filter((t) => t.error);

  // Collect param keys for column display
  const paramKeys = report.trials.length > 0 ? Object.keys(report.trials[0].params).sort() : [];

  return (
    <Card className="overflow-hidden" data-testid="param-compare-panel">
      <CardHeader className="bg-muted/50 pb-3">
        <div className="flex items-center gap-2">
          <Trophy className="h-4 w-4 text-primary" />
          <CardTitle className="text-base">参数对比</CardTitle>
        </div>
        <CardDescription>
          {passing.length} 成功 / {failed.length} 失败 / 共 {report.total_combinations} 组合
          {report.max_workers > 1 && ` (${report.max_workers} 并行)`}
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-4">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="param-compare-table">
            <thead>
              <tr className="border-b text-left">
                <th className="px-2 py-1 font-medium text-muted-foreground">#</th>
                {paramKeys.map((k) => (
                  <th key={k} className="px-2 py-1 font-medium text-muted-foreground">
                    {k}
                  </th>
                ))}
                {COMPARISON_METRICS.map((metric) => (
                  <th
                    key={metric}
                    className="cursor-pointer select-none px-2 py-1 font-medium text-muted-foreground hover:text-foreground"
                    onClick={() => handleSort(metric)}
                    data-testid={`sort-${metric}`}
                  >
                    <span className="inline-flex items-center gap-1">
                      {METRIC_LABELS[metric] || metric}
                      {sortMetric === metric && sortDir && (
                        <ArrowUpDown className="h-3 w-3" />
                      )}
                    </span>
                  </th>
                ))}
                <th className="px-2 py-1 font-medium text-muted-foreground">耗时</th>
              </tr>
            </thead>
            <tbody>
              {trials.map((trial) => {
                const isFailed = !!trial.error;
                const passingIdx = passing.indexOf(trial);
                return (
                  <tr
                    key={trial.trial_index}
                    className={`border-b ${isFailed ? 'opacity-50' : 'hover:bg-muted/40'}`}
                    data-testid={`param-trial-${trial.trial_index}`}
                  >
                    <td className="px-2 py-1 font-mono text-muted-foreground">
                      {trial.trial_index + 1}
                    </td>
                    {paramKeys.map((k) => (
                      <td key={k} className="px-2 py-1 font-mono">
                        {String(trial.params[k] ?? '—')}
                      </td>
                    ))}
                    {COMPARISON_METRICS.map((metric) => {
                      const val = trial.metrics[metric];
                      const isBest = passingIdx >= 0 && bestTrials.get(metric) === passingIdx;
                      return (
                        <td
                          key={metric}
                          className={`px-2 py-1 font-mono ${isBest ? 'font-bold text-primary' : ''}`}
                          data-testid={`trial-${trial.trial_index}-${metric}`}
                        >
                          {formatMetricValue(metric, val as number | null)}
                          {isBest && <span className="ml-1 text-yellow-500">★</span>}
                        </td>
                      );
                    })}
                    <td className="px-2 py-1 font-mono text-muted-foreground">
                      {trial.duration_seconds.toFixed(1)}s
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Failed trials summary */}
        {failed.length > 0 && (
          <div className="mt-3 space-y-1" data-testid="param-compare-failed">
            <p className="text-sm font-medium text-destructive">失败组合:</p>
            {failed.map((t) => (
              <p key={t.trial_index} className="text-xs text-muted-foreground">
                #{t.trial_index + 1} {_paramSummary(t.params)}: {t.error || '未知错误'}
              </p>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
