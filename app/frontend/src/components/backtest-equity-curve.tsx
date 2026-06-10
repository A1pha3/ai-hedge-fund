import { useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

// ============================================================
// P0-4: 回测净值曲线可视化 (Equity Curve Visualization)
// ============================================================
//
// Uses the backtestResults array from agentData['backtest'] to render:
// 1. Equity curve (CSS-based area chart)
// 2. Drawdown curve
// 3. Monthly returns heatmap
//
// No external chart library required — pure CSS + SVG rendering.
// The data comes from the streaming endpoint's per-day results
// (same data the BacktestTradingTable already consumes).
// ============================================================

interface BacktestDayResult {
  date: string;
  portfolio_value: number;
  portfolio_return?: number;
  cash?: number;
}

interface EquityCurveProps {
  agentData: Record<string, any>;
}

// --- KPI Cards ---

function KpiCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="text-center p-3 rounded-lg bg-muted/30">
      <div className="text-xs text-muted-foreground mb-1">{label}</div>
      <div className={cn("text-lg font-semibold", color)}>
        {value}
      </div>
    </div>
  );
}

// --- Equity Curve SVG ---

function EquityCurveChart({ points }: { points: { date: string; value: number; drawdown: number }[] }) {
  if (points.length < 2) return null;

  const values = points.map(p => p.value).filter(v => isFinite(v));
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const width = 800;
  const height = 200;
  const padding = { top: 10, right: 10, bottom: 30, left: 60 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;
  const bottomY = padding.top + chartH; // R20.29: 前置声明, 避免 .map 回调引用 TDZ 变量

  const pointsStr = points
    .filter(p => isFinite(p.value))
    .map((p, i, arr) => {
      const x = padding.left + (i / (arr.length - 1)) * chartW;
      const y = padding.top + (1 - (p.value - min) / range) * chartH;
      return `${x},${isFinite(y) ? y : bottomY}`;
    })
    .join(' ');

  // Area path (filled)
  const firstX = padding.left;
  const lastX = padding.left + chartW;
  const areaPath = `M${firstX},${bottomY} L${pointsStr.split(' ').map((p, i) => {
    const [x, y] = p.split(',');
    return i === 0 ? `${x},${y}` : ` L${x},${y}`;
  }).join('')} L${lastX},${bottomY} Z`;

  // Y-axis labels
  const yLabels = [0, 0.25, 0.5, 0.75, 1].map(t => ({
    y: padding.top + (1 - t) * chartH,
    value: min + t * range,
  }));

  // X-axis labels (first, middle, last)
  const xLabels = [
    { idx: 0, label: points[0].date },
    { idx: Math.floor(points.length / 2), label: points[Math.floor(points.length / 2)].date },
    { idx: points.length - 1, label: points[points.length - 1].date },
  ];

  // R20.15 GAMMA A-1: aria-label summarizing curve for screen readers
  const startVal = points[0].value;
  const endVal = points[points.length - 1].value;
  const startWan = (startVal / 1e4).toFixed(0);
  const endWan = (endVal / 1e4).toFixed(0);
  const totalRetPct = (((endVal - startVal) / startVal) * 100).toFixed(2);
  const ariaLabel = `回测净值曲线: ${points.length} 个交易日, 从 ¥${startWan}万 到 ¥${endWan}万, 总收益 ${totalRetPct}%`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-48"
      role="img"
      aria-label={ariaLabel}
    >
      {/* Grid lines */}
      {yLabels.map((l, i) => (
        <g key={i}>
          <line x1={padding.left} y1={l.y} x2={width - padding.right} y2={l.y}
            stroke="currentColor" strokeOpacity={0.1} />
          <text x={padding.left - 4} y={l.y + 4} textAnchor="end"
            className="fill-muted-foreground text-[10px]">
            {(l.value / 1e4).toFixed(0)}万
          </text>
        </g>
      ))}
      {/* X labels */}
      {xLabels.map((l, i) => (
        <text key={i}
          x={padding.left + (l.idx / (points.length - 1)) * chartW}
          y={height - 5}
          textAnchor="middle"
          className="fill-muted-foreground text-[10px]">
          {l.label}
        </text>
      ))}
      {/* Area fill */}
      <path d={areaPath} fill="currentColor" fillOpacity={0.1} className="text-cyan-500" />
      {/* Line */}
      <polyline
        points={pointsStr}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        className="text-cyan-500"
      />
    </svg>
  );
}

// --- Drawdown Chart ---

function DrawdownChart({ points }: { points: { date: string; drawdown: number }[] }) {
  if (points.length < 2) return null;

  const drawdowns = points.map(p => p.drawdown).filter(d => isFinite(d));
  const maxDD = Math.max(...drawdowns, 0.01); // at least 1%

  const width = 800;
  const height = 100;
  const padding = { top: 5, right: 10, bottom: 20, left: 60 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;
  const topY = padding.top; // R20.29: 前置声明, 避免 .map 回调引用 TDZ 变量

  const pointsStr = points
    .filter(p => isFinite(p.drawdown))
    .map((p, i, arr) => {
      const x = padding.left + (i / (arr.length - 1)) * chartW;
      const y = padding.top + (p.drawdown / maxDD) * chartH;
      return `${x},${isFinite(y) ? y : topY}`;
    })
    .join(' ');

  const firstX = padding.left;
  const lastX = padding.left + chartW;
  const areaPath = `M${firstX},${topY} L${pointsStr.split(' ').map((p, i) => {
    const [x, y] = p.split(',');
    return i === 0 ? `${x},${y}` : ` L${x},${y}`;
  }).join('')} L${lastX},${topY} Z`;

  // R20.15 GAMMA A-2: aria-label for drawdown chart
  const drawdownAriaLabel = `最大回撤图: 最大回撤 ${(maxDD * 100).toFixed(1)}%`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-24"
      role="img"
      aria-label={drawdownAriaLabel}
    >
      {/* Area fill */}
      <path d={areaPath} fill="currentColor" fillOpacity={0.15} className="text-red-500" />
      {/* Line */}
      <polyline
        points={pointsStr}
        fill="none"
        stroke="currentColor"
        strokeWidth={1}
        className="text-red-500"
      />
      {/* Max drawdown label */}
      <text x={padding.left + 4} y={padding.top + 14} className="fill-red-400 text-[10px]">
        最大回撤: {(maxDD * 100).toFixed(1)}%
      </text>
    </svg>
  );
}

// --- Monthly Returns Heatmap ---

function MonthlyReturnsHeatmap({ dailyResults }: { dailyResults: BacktestDayResult[] }) {
  const monthlyReturns = useMemo(() => {
    const map: Record<string, number[]> = {};
    dailyResults.forEach((day, i) => {
      if (!day.date) return;
      const ym = day.date.slice(0, 7); // YYYY-MM
      const ret = i > 0
        ? (day.portfolio_value - dailyResults[i - 1].portfolio_value) / dailyResults[i - 1].portfolio_value
        : 0;
      map[ym] = map[ym] || [];
      map[ym].push(ret);
    });

    return Object.entries(map)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([ym, returns]) => {
        const compound = returns.reduce((acc, r) => acc * (1 + r), 1) - 1;
        return { ym, return_pct: compound };
      });
  }, [dailyResults]);

  if (monthlyReturns.length === 0) return null;

  const getColor = (ret: number) => {
    if (ret > 0.05) return 'bg-green-600 text-white';
    if (ret > 0.02) return 'bg-green-500/70 text-white';
    if (ret > 0) return 'bg-green-400/50 text-foreground';
    if (ret > -0.02) return 'bg-red-400/50 text-foreground';
    if (ret > -0.05) return 'bg-red-500/70 text-white';
    return 'bg-red-600 text-white';
  };

  return (
    <div className="mt-3">
      <h4 className="text-xs text-muted-foreground mb-2">月度收益热力图</h4>
      <div className="flex flex-wrap gap-1">
        {monthlyReturns.map(({ ym, return_pct }) => (
          <div
            key={ym}
            className={cn(
              "px-2 py-1 rounded text-xs font-mono min-w-[80px] text-center",
              getColor(return_pct)
            )}
            title={`${ym}: ${(return_pct * 100).toFixed(2)}%`}
          >
            <div className="text-[10px] opacity-70">{ym}</div>
            <div className="font-semibold">{(return_pct * 100).toFixed(1)}%</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// --- Main Component ---

export function BacktestEquityCurve({ agentData }: EquityCurveProps) {
  const backtestAgent = agentData['backtest'];
  if (!backtestAgent || !backtestAgent.backtestResults) return null;

  const dailyResults: BacktestDayResult[] = backtestAgent.backtestResults || [];
  if (dailyResults.length < 2) return null;

  // Compute derived data
  const initialValue = dailyResults[0].portfolio_value;
  const currentValue = dailyResults[dailyResults.length - 1].portfolio_value;

  // Guard against NaN / Infinity from malformed data
  if (!isFinite(initialValue) || !isFinite(currentValue) || initialValue === 0) return null;

  const totalReturn = (currentValue - initialValue) / initialValue;

  // Compute equity curve points with drawdown
  // R20.15 GAMMA E-2: drop individual days with NaN/Infinity portfolio_value
  // before they propagate into the SVG (which silently renders broken paths).
  let peak = initialValue;
  const points = dailyResults
    .filter(day => isFinite(day.portfolio_value))
    .map(day => {
      if (day.portfolio_value > peak) peak = day.portfolio_value;
      const drawdown = peak > 0 ? (peak - day.portfolio_value) / peak : 0;
      return {
        date: day.date,
        value: day.portfolio_value,
        drawdown,
        daily_return: day.portfolio_return || 0,
      };
    });
  if (points.length < 2) return null;

  const maxDrawdown = Math.max(...points.map(p => p.drawdown));
  const winningDays = points.filter(p => p.daily_return > 0).length;
  const winRate = points.length > 0 ? (winningDays / points.length) * 100 : 0;

  return (
    <Card className="bg-transparent mb-4">
      <CardHeader className="pb-2">
        <CardTitle className="text-lg">回测净值曲线</CardTitle>
      </CardHeader>
      <CardContent>
        {/* KPI Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-4">
          <KpiCard
            label="总收益"
            value={`${totalReturn >= 0 ? '+' : ''}${(totalReturn * 100).toFixed(2)}%`}
            color={totalReturn >= 0 ? 'text-green-500' : 'text-red-500'}
          />
          <KpiCard
            label="最大回撤"
            value={`${(maxDrawdown * 100).toFixed(2)}%`}
            color="text-red-500"
          />
          <KpiCard label="胜率" value={`${winRate.toFixed(1)}%`} />
          <KpiCard label="交易天数" value={`${dailyResults.length}`} />
          <KpiCard
            label="初始资金"
            value={`¥${(initialValue / 1e4).toFixed(0)}万`}
          />
          <KpiCard
            label="最终资金"
            value={`¥${(currentValue / 1e4).toFixed(0)}万`}
            color={totalReturn >= 0 ? 'text-green-500' : 'text-red-500'}
          />
        </div>

        {/* Equity Curve */}
        <EquityCurveChart points={points} />

        {/* Drawdown Curve */}
        <div className="mt-2">
          <h4 className="text-xs text-muted-foreground mb-1">水下图 (Drawdown)</h4>
          <DrawdownChart points={points} />
        </div>

        {/* Monthly Returns Heatmap */}
        <MonthlyReturnsHeatmap dailyResults={dailyResults} />
      </CardContent>
    </Card>
  );
}
