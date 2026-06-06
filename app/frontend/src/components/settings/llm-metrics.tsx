import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import {
  fetchLLMMetricsSummary,
  type LLMMetricsSummary,
  type AgentMetrics,
  type DailyMetrics,
  type DailyProviderEntry,
} from '@/services/llm-metrics-api';
import { Activity, Clock, Zap, AlertTriangle } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatChars(n: number): string {
  if (n < 1000) return `${n}`;
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

// Heatmap color scale: low duration = cool, high duration = hot
function durationHeatColor(value: number, min: number, max: number): string {
  if (max === min) return 'rgba(59, 130, 246, 0.15)';
  const t = Math.min(1, Math.max(0, (value - min) / (max - min)));
  // Green -> Yellow -> Red
  if (t < 0.5) {
    const ratio = t * 2;
    const r = Math.round(34 + ratio * (234 - 34));
    const g = Math.round(197 + ratio * (179 - 197));
    const b = Math.round(94 + ratio * (8 - 94));
    return `rgba(${r}, ${g}, ${b}, 0.35)`;
  } else {
    const ratio = (t - 0.5) * 2;
    const r = Math.round(234 + ratio * (239 - 234));
    const g = Math.round(179 - ratio * 179);
    const b = Math.round(8 + ratio * (68 - 8));
    return `rgba(${r}, ${g}, ${b}, 0.4)`;
  }
}

interface SummaryCardProps {
  label: string;
  value: string;
  sub?: string;
  icon: React.ReactNode;
  className?: string;
}

function SummaryCard({ label, value, sub, icon, className }: SummaryCardProps) {
  return (
    <div className={cn('rounded-lg border border-border/40 bg-card/50 p-4', className)}>
      <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
        {icon}
        {label}
      </div>
      <div className="text-xl font-semibold text-primary">{value}</div>
      {sub && <div className="text-xs text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}

interface AgentHeatmapGridProps {
  agents: AgentMetrics[];
  metric: 'avg_duration_ms' | 'p95_duration_ms' | 'calls';
  label: string;
}

function AgentHeatmapGrid({ agents, metric, label }: AgentHeatmapGridProps) {
  if (agents.length === 0) return null;

  const values = agents.map((a) => a[metric]);
  const min = Math.min(...values);
  const max = Math.max(...values);

  return (
    <div>
      <h3 className="text-sm font-medium text-primary mb-2">{label}</h3>
      <div className="grid gap-1.5" style={{ gridTemplateColumns: '200px 1fr 80px' }}>
        {/* Header */}
        <div className="text-xs text-muted-foreground px-2 py-1">Agent</div>
        <div className="text-xs text-muted-foreground px-2 py-1">Value</div>
        <div className="text-xs text-muted-foreground px-2 py-1 text-right">Raw</div>
        {/* Rows */}
        {agents.map((agent) => {
          const val = agent[metric];
          const bg = durationHeatColor(val, min, max);
          const barWidth = max > 0 ? `${Math.max(5, (val / max) * 100)}%` : '0%';
          return (
            <div key={agent.agent_name} className="contents">
              <div className="text-xs text-primary truncate px-2 py-1.5 flex items-center" title={agent.agent_name}>
                {agent.agent_name.replace(/_agent$/, '').replace(/_/g, ' ')}
              </div>
              <div className="relative h-7 flex items-center px-2 py-1.5 rounded" style={{ background: bg }}>
                <div
                  className="absolute left-0 top-0 h-full rounded opacity-20"
                  style={{ width: barWidth, background: 'currentColor' }}
                />
                <span className="relative text-xs font-medium text-primary">
                  {metric === 'calls' ? `${val}` : formatMs(val)}
                </span>
              </div>
              <div className="text-xs text-muted-foreground px-2 py-1.5 text-right font-mono">
                {metric === 'calls' ? val : `${Math.round(val)}ms`}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface DailyTrendChartProps {
  daily: DailyMetrics[];
}

function DailyTrendChart({ daily }: DailyTrendChartProps) {
  if (daily.length === 0) return null;

  const maxCalls = Math.max(...daily.map((d) => d.calls));
  const maxDuration = Math.max(...daily.map((d) => d.avg_duration_ms));

  return (
    <div>
      <h3 className="text-sm font-medium text-primary mb-2">Daily Trend</h3>
      <div className="flex gap-1.5 items-end" style={{ height: 80 }}>
        {daily.map((d) => {
          const callHeight = maxCalls > 0 ? (d.calls / maxCalls) * 100 : 0;
          const durHeight = maxDuration > 0 ? (d.avg_duration_ms / maxDuration) * 100 : 0;
          return (
            <div key={d.date} className="flex-1 flex flex-col items-center gap-0.5 min-w-0" title={`${d.date}: ${d.calls} calls, avg ${formatMs(d.avg_duration_ms)}`}>
              <div className="relative w-full flex items-end justify-center gap-px" style={{ height: 50 }}>
                {/* Calls bar */}
                <div
                  className="w-1/2 bg-blue-500/40 rounded-t"
                  style={{ height: `${callHeight}%`, minHeight: d.calls > 0 ? 2 : 0 }}
                />
                {/* Duration bar */}
                <div
                  className="w-1/2 bg-amber-500/40 rounded-t"
                  style={{ height: `${durHeight}%`, minHeight: d.avg_duration_ms > 0 ? 2 : 0 }}
                />
              </div>
              <div className="text-[10px] text-muted-foreground truncate w-full text-center">
                {d.date.slice(5)}
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex gap-4 mt-2">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <div className="w-3 h-2 bg-blue-500/40 rounded-sm" /> Calls
        </div>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <div className="w-3 h-2 bg-amber-500/40 rounded-sm" /> Avg Duration
        </div>
      </div>
    </div>
  );
}

interface LLMMetricsPanelProps {
  className?: string;
}

export function LLMMetricsPanel({ className }: LLMMetricsPanelProps) {
  const [data, setData] = useState<LLMMetricsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchLLMMetricsSummary(7)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load LLM metrics');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className={cn('flex items-center justify-center py-12 text-muted-foreground text-sm', className)}>
        Loading LLM metrics...
      </div>
    );
  }

  if (error) {
    return (
      <div className={cn('flex items-center justify-center py-12 text-destructive text-sm', className)}>
        Error: {error}
      </div>
    );
  }

  if (!data || data.totals.calls === 0) {
    return (
      <div className={cn('flex flex-col items-center justify-center py-12 gap-2', className)}>
        <Activity className="h-8 w-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">No LLM metrics data available for the last {data?.lookback_days ?? 7} days.</p>
        <p className="text-xs text-muted-foreground">Run a hedge fund analysis to generate metrics.</p>
      </div>
    );
  }

  const { totals, agents, daily_trend } = data;
  const errorRate = totals.calls > 0 ? ((totals.errors / totals.calls) * 100).toFixed(1) : '0.0';

  // Sort agents by total_duration desc for the duration heatmap
  const agentsByDuration = [...agents].sort((a, b) => b.total_duration_ms - a.total_duration_ms);
  const agentsByCalls = [...agents].sort((a, b) => b.calls - a.calls);

  return (
    <div className={cn('space-y-6', className)}>
      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <SummaryCard
          label="Total Calls"
          value={`${totals.calls.toLocaleString()}`}
          sub={`${totals.successes} ok, ${totals.errors} errors`}
          icon={<Zap className="h-3.5 w-3.5" />}
        />
        <SummaryCard
          label="Avg Latency"
          value={formatMs(totals.avg_duration_ms)}
          sub={`Across ${totals.sessions_scanned} session(s)`}
          icon={<Clock className="h-3.5 w-3.5" />}
        />
        <SummaryCard
          label="Total I/O"
          value={`${formatChars(totals.prompt_chars + totals.response_chars)}`}
          sub={`${formatChars(totals.prompt_chars)} in / ${formatChars(totals.response_chars)} out`}
          icon={<Activity className="h-3.5 w-3.5" />}
        />
        <SummaryCard
          label="Error Rate"
          value={`${errorRate}%`}
          sub={totals.errors > 0 ? `${totals.errors} failed calls` : 'No errors'}
          icon={<AlertTriangle className="h-3.5 w-3.5" />}
          className={totals.errors > 0 ? 'border-amber-600/40' : undefined}
        />
      </div>

      {/* Agent Latency Heatmap */}
      <AgentHeatmapGrid agents={agentsByDuration} metric="avg_duration_ms" label="Agent Latency (avg)" />
      <AgentHeatmapGrid agents={agentsByDuration} metric="p95_duration_ms" label="Agent Latency (P95)" />

      {/* Agent Call Volume */}
      <AgentHeatmapGrid agents={agentsByCalls} metric="calls" label="Agent Call Volume" />

      {/* P2 6.4: Cost Heatmap Panels */}
      {data.providers && data.providers.length > 0 && (
        <ProviderCostLatencyPanels
          providers={data.providers}
          topByLatency={data.top_providers_by_latency}
          topAgentsByCost={data.top_agents_by_cost}
        />
      )}

      {data.cost_savings_suggestions && data.cost_savings_suggestions.length > 0 && (
        <CostSavingsSuggestionsCard suggestions={data.cost_savings_suggestions} />
      )}

      {data.daily_provider && data.daily_provider.length > 0 && (
        <DailyProviderHeatmap days={data.daily_provider} />
      )}

      {/* Daily Trend */}
      <DailyTrendChart daily={daily_trend} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// P2 6.4: Cost / latency heatmap panels
// ---------------------------------------------------------------------------

function formatUsd(value: number | undefined): string {
  if (value === undefined || value === null) return '--';
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function ProviderCostLatencyPanels({
  providers,
  topByLatency,
  topAgentsByCost,
}: {
  providers: LLMMetricsSummary['providers'] | undefined;
  topByLatency: LLMMetricsSummary['top_providers_by_latency'];
  topAgentsByCost: LLMMetricsSummary['top_agents_by_cost'];
}) {
  if (!providers) return null;
  // Build a per-provider cost bar chart.
  const sortedByCost = [...providers].sort(
    (a, b) => (b.estimated_cost_usd ?? 0) - (a.estimated_cost_usd ?? 0),
  );
  const maxCost = Math.max(1, ...sortedByCost.map(p => p.estimated_cost_usd ?? 0));
  return (
    <div className="space-y-4" data-testid="provider-cost-latency-panels">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Provider Cost &amp; Latency</CardTitle>
          <CardDescription>按 provider 聚合的成本 / 延迟柱状图</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {sortedByCost.map(p => {
            const costPct = ((p.estimated_cost_usd ?? 0) / maxCost) * 100;
            return (
              <div
                key={p.provider}
                className="space-y-1"
                data-testid="provider-cost-row"
                data-provider={p.provider}
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono">{p.provider}</span>
                  <span className="text-muted-foreground">
                    {formatUsd(p.estimated_cost_usd)} · {formatMs(p.avg_duration_ms)} avg
                  </span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full bg-blue-500/80"
                    style={{ width: `${costPct}%` }}
                    data-testid="provider-cost-bar"
                  />
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {/* Top-5 slowest providers (already sorted by latency desc) */}
      {topByLatency && topByLatency.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Top {topByLatency.length} Slowest Providers</CardTitle>
            <CardDescription>平均延迟倒序,可作为 health-check 关注对象</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {topByLatency.map(p => (
                <div
                  key={p.provider}
                  data-testid="slow-provider-row"
                  data-provider={p.provider}
                  className="flex items-center justify-between rounded-md border border-border/40 bg-muted/10 px-3 py-2 text-xs"
                >
                  <span className="font-mono">{p.provider}</span>
                  <span>
                    {formatMs(p.avg_duration_ms)} avg · {formatMs(p.p95_duration_ms)} p95 ·{' '}
                    {(p.error_rate * 100).toFixed(1)}% err
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Top agents by cost */}
      {topAgentsByCost && topAgentsByCost.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Top {topAgentsByCost.length} Most Expensive Agents</CardTitle>
            <CardDescription>累计花费最高的 agent — 是成本节省的优先目标</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {topAgentsByCost.map(a => (
                <div
                  key={a.agent_name}
                  data-testid="expensive-agent-row"
                  data-agent={a.agent_name}
                  className="flex items-center justify-between rounded-md border border-border/40 bg-muted/10 px-3 py-2 text-xs"
                >
                  <span className="font-mono">{a.agent_name}</span>
                  <span>
                    {formatUsd(a.estimated_cost_usd)} · {a.calls} calls ·{' '}
                    {formatUsd(a.calls > 0 ? (a.estimated_cost_usd ?? 0) / a.calls : 0)} /call
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function CostSavingsSuggestionsCard({
  suggestions,
}: {
  suggestions: NonNullable<LLMMetricsSummary['cost_savings_suggestions']>;
}) {
  return (
    <Card data-testid="cost-savings-suggestions">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Cost-Saving Suggestions</CardTitle>
        <CardDescription>
          单次调用成本 ≥ 2 倍全局中位数的 agent — 切换更便宜的模型可显著降低费用
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {suggestions.map(s => (
            <li
              key={s.agent_name}
              data-testid="cost-savings-suggestion"
              data-agent={s.agent_name}
              className="flex items-center justify-between rounded-md border border-amber-500/40 bg-amber-50/40 px-3 py-2 text-xs dark:bg-amber-950/20"
            >
              <span>
                <span className="font-mono font-medium">{s.agent_name}</span>
                <span className="text-muted-foreground">
                  {' '}
                  当前 {formatUsd(s.current_cost_per_call)} /call
                </span>
              </span>
              <span className="text-amber-700 dark:text-amber-300">
                可省 {s.potential_savings_pct.toFixed(0)}% · {s.calls} 次调用
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function DailyProviderHeatmap({
  days,
}: {
  days: NonNullable<LLMMetricsSummary['daily_provider']>;
}) {
  // Collect the full provider list across the window so the grid is
  // rectangular even when some providers didn't run on some days.
  const providerSet = new Set<string>();
  for (const d of days) for (const p of d.providers) providerSet.add(p.provider);
  const providers = Array.from(providerSet).sort();
  // Build lookup
  const matrix: Record<string, Record<string, DailyProviderEntry | undefined>> = {};
  for (const d of days) {
    matrix[d.date] = {};
    for (const p of d.providers) matrix[d.date][p.provider] = p;
  }
  return (
    <Card data-testid="daily-provider-heatmap">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Provider × Day Error-Rate Heatmap</CardTitle>
        <CardDescription>
          红色 = 高错误率 / 灰色 = 无调用 / 浅绿 = 健康
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr>
                <th className="text-left p-1">provider</th>
                {days.map(d => (
                  <th key={d.date} className="p-1 font-mono text-muted-foreground">
                    {d.date.slice(5)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {providers.map(provider => (
                <tr key={provider} data-testid="heatmap-row" data-provider={provider}>
                  <td className="p-1 font-mono">{provider}</td>
                  {days.map(d => {
                    const cell = matrix[d.date]?.[provider];
                    if (!cell) {
                      return (
                        <td
                          key={d.date}
                          className="p-1 text-center bg-muted/30 text-muted-foreground"
                        >
                          ·
                        </td>
                      );
                    }
                    let color = 'bg-green-200 dark:bg-green-900/40';
                    if (cell.error_rate >= 0.2) color = 'bg-red-300 dark:bg-red-900/50';
                    else if (cell.error_rate >= 0.1) color = 'bg-amber-200 dark:bg-amber-900/40';
                    return (
                      <td
                        key={d.date}
                        className={`p-1 text-center ${color}`}
                        title={`${cell.calls} calls, ${(cell.error_rate * 100).toFixed(1)}% err`}
                      >
                        {cell.calls}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
