import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import {
  fetchLLMMetricsSummary,
  type LLMMetricsSummary,
  type AgentMetrics,
  type DailyMetrics,
} from '@/services/llm-metrics-api';
import { Activity, Clock, Zap, AlertTriangle } from 'lucide-react';

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

      {/* Daily Trend */}
      <DailyTrendChart daily={daily_trend} />
    </div>
  );
}
