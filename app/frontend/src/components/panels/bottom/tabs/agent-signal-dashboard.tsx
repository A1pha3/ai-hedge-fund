/**
 * P2-1 Agent Signal Dashboard — visual summary of multi-agent signals.
 *
 * Replaces the flat table in RegularOutput with:
 * - Consensus bar (bullish/bearish/neutral distribution)
 * - Consensus summary text
 * - Grouped agent signal cards (by direction)
 * - Expandable reasoning per agent
 *
 * Uses existing pure helpers from agent-signal-helpers.ts (contradiction detection)
 * and agent-signal-dashboard-helpers.ts (consensus stats).
 */

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { detectContradiction } from '@/nodes/components/agent-signal-helpers';
import type { AgentSignalEntry } from '@/nodes/components/agent-signal-helpers';
import { cn } from '@/lib/utils';
import {
  categorizeAgents,
  computeConsensusStats,
  getConsensusSummary,
  truncateReasoning,
} from './agent-signal-dashboard-helpers';
import { ReasoningContent } from './reasoning-content';
import { AlertTriangle, ArrowDown, ArrowUp, Minus, TrendingUp, TrendingDown, Scale } from 'lucide-react';
import { useState } from 'react';

// ---------- Sub-components ----------

/** Consensus distribution bar — horizontal stacked bar showing signal distribution */
function ConsensusBar({ stats }: { stats: ReturnType<typeof computeConsensusStats> }) {
  const { total, bullish, bearish, neutral } = stats;
  if (total === 0) return null;

  const bullishPct = (bullish / total) * 100;
  const bearishPct = (bearish / total) * 100;
  const neutralPct = (neutral / total) * 100;

  return (
    <div className="space-y-2">
      <div className="flex h-3 w-full rounded-full overflow-hidden bg-muted">
        {bullishPct > 0 && (
          <div className="bg-green-500 transition-all duration-500" style={{ width: `${bullishPct}%` }} />
        )}
        {neutralPct > 0 && (
          <div className="bg-muted-foreground/40 transition-all duration-500" style={{ width: `${neutralPct}%` }} />
        )}
        {bearishPct > 0 && (
          <div className="bg-red-500 transition-all duration-500" style={{ width: `${bearishPct}%` }} />
        )}
      </div>
      <div className="flex justify-between text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <ArrowUp className="h-3 w-3 text-green-500" />
          看多 {bullish} ({bullishPct.toFixed(0)}%)
        </span>
        <span className="flex items-center gap-1">
          <Minus className="h-3 w-3 text-muted-foreground" />
          中性 {neutral}
        </span>
        <span className="flex items-center gap-1">
          <ArrowDown className="h-3 w-3 text-red-500" />
          看空 {bearish} ({bearishPct.toFixed(0)}%)
        </span>
      </div>
    </div>
  );
}

/** Consensus direction badge — shows overall market sentiment */
function ConsensusBadge({ stats }: { stats: ReturnType<typeof computeConsensusStats> }) {
  const { consensusDirection, consensusStrength } = stats;

  const config: Record<string, { icon: typeof TrendingUp; label: string; className: string }> = {
    bullish: { icon: TrendingUp, label: '偏多', className: 'bg-green-500/10 text-green-500 border-green-500/20' },
    bearish: { icon: TrendingDown, label: '偏空', className: 'bg-red-500/10 text-red-500 border-red-500/20' },
    neutral: { icon: Scale, label: '中性', className: 'bg-muted/10 text-muted-foreground border-muted/20' },
    divided: { icon: AlertTriangle, label: '分歧', className: 'bg-yellow-500/10 text-yellow-500 border-yellow-500/20' },
  };

  const { icon: Icon, label, className } = config[consensusDirection] || config.neutral;
  const strengthLabel = consensusStrength >= 0.8 ? '强' : consensusStrength >= 0.6 ? '中' : '弱';

  return (
    <div className={cn('inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-sm font-medium', className)}>
      <Icon className="h-4 w-4" />
      <span>{label} ({strengthLabel})</span>
    </div>
  );
}

/** Single agent signal card — shows agent name, signal badge, confidence bar, reasoning preview */
function AgentSignalCard({ entry, isHighlighted }: { entry: AgentSignalEntry; isHighlighted: boolean }) {
  const signalConfig: Record<string, { label: string; className: string; icon: typeof ArrowUp }> = {
    bullish: { label: '看多', className: 'bg-green-500/10 text-green-500 border-green-500/20', icon: ArrowUp },
    bearish: { label: '看空', className: 'bg-red-500/10 text-red-500 border-red-500/20', icon: ArrowDown },
    neutral: { label: '中性', className: 'bg-muted/10 text-muted-foreground border-muted/20', icon: Minus },
  };

  const { label, className, icon: SignalIcon } = signalConfig[entry.signal] || signalConfig.neutral;

  return (
    <div className={cn(
      'rounded-lg border p-3 transition-colors',
      isHighlighted ? 'border-yellow-500/40 bg-yellow-500/5' : 'border-border bg-card',
    )}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm">{entry.displayName}</span>
          {isHighlighted && (
            <AlertTriangle className="h-3.5 w-3.5 text-yellow-500" />
          )}
        </div>
        <div className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-medium', className)}>
          <SignalIcon className="h-3 w-3" />
          {label}
        </div>
      </div>

      {/* Confidence bar */}
      <div className="space-y-1 mb-2">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>置信度</span>
          <span className="font-mono">{entry.confidence}%</span>
        </div>
        <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
          <div
            className={cn(
              'h-full rounded-full transition-all duration-500',
              entry.signal === 'bullish' ? 'bg-green-500' :
              entry.signal === 'bearish' ? 'bg-red-500' :
              'bg-muted-foreground',
            )}
            style={{ width: `${Math.min(100, Math.max(0, entry.confidence))}%` }}
          />
        </div>
      </div>

      {/* Reasoning preview (expandable) */}
      {entry.reasoning && (
        <Accordion type="single" collapsible className="w-full">
          <AccordionItem value="reasoning" className="border-b-0">
            <AccordionTrigger className="py-1 text-xs text-muted-foreground hover:no-underline">
              {truncateReasoning(entry.reasoning, 60)}
            </AccordionTrigger>
            <AccordionContent className="pb-0">
              <div className="text-xs text-muted-foreground leading-relaxed">
                <ReasoningContent content={entry.reasoning} />
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      )}
    </div>
  );
}

/** Group of agent cards sharing the same signal direction */
function AgentGroup({ category, highlightedIds }: { category: ReturnType<typeof categorizeAgents>[0]; highlightedIds: Set<string> }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className={cn('text-sm font-semibold', category.colorClass)}>{category.label}</span>
        <Badge variant={category.badgeVariant as "secondary" | "destructive" | "success" | "warning" | "outline"} className="text-xs">
          {category.agents.length}
        </Badge>
      </div>
      <div className="grid grid-cols-1 gap-2">
        {category.agents.map(entry => (
          <AgentSignalCard
            key={entry.agentId}
            entry={entry}
            isHighlighted={highlightedIds.has(entry.agentId)}
          />
        ))}
      </div>
    </div>
  );
}

// ---------- Main Component ----------

export interface AgentSignalDashboardProps {
  /** Agent signal entries for the current ticker, pre-built via buildAgentSignalsForTicker */
  entries: AgentSignalEntry[];
  /** Ticker symbol for display */
  ticker: string;
}

export function AgentSignalDashboard({ entries, ticker }: AgentSignalDashboardProps) {
  const [viewMode, setViewMode] = useState<'grouped' | 'list'>('grouped');

  if (entries.length === 0) {
    return (
      <Card className="bg-transparent">
        <CardContent className="py-8 text-center text-muted-foreground">
          无 {ticker} 的 Agent 信号数据
        </CardContent>
      </Card>
    );
  }

  const stats = computeConsensusStats(entries);
  const contradiction = detectContradiction(entries, { highConfidenceThreshold: 70 });
  const categories = categorizeAgents(entries);
  const summary = getConsensusSummary(stats);

  return (
    <div className="space-y-4">
      {/* Consensus Overview Card */}
      <Card className="bg-transparent">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Agent 共识 — {ticker}</CardTitle>
            <ConsensusBadge stats={stats} />
          </div>
          <CardDescription className="text-xs mt-1">{summary}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Consensus bar */}
          <ConsensusBar stats={stats} />

          {/* Contradiction alert */}
          {contradiction.hasContradiction && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/20">
              <AlertTriangle className="h-4 w-4 text-yellow-500 mt-0.5 flex-shrink-0" />
              <div className="text-sm">
                <span className="font-medium text-yellow-500">信号分歧</span>
                <span className="text-muted-foreground ml-1">{contradiction.summary}</span>
              </div>
            </div>
          )}

          {/* Average confidence */}
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>平均置信度: <span className="font-mono font-medium text-foreground">{stats.avgConfidence.toFixed(1)}%</span></span>
            <span className="text-border">|</span>
            <span>参与 Agents: <span className="font-medium text-foreground">{stats.total}</span></span>
          </div>
        </CardContent>
      </Card>

      {/* View mode toggle */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setViewMode('grouped')}
          className={cn(
            'px-3 py-1 text-xs rounded-md border transition-colors',
            viewMode === 'grouped'
              ? 'bg-primary text-primary-foreground border-primary'
              : 'bg-transparent text-muted-foreground border-border hover:bg-accent',
          )}
        >
          按方向分组
        </button>
        <button
          onClick={() => setViewMode('list')}
          className={cn(
            'px-3 py-1 text-xs rounded-md border transition-colors',
            viewMode === 'list'
              ? 'bg-primary text-primary-foreground border-primary'
              : 'bg-transparent text-muted-foreground border-border hover:bg-accent',
          )}
        >
          全部列表
        </button>
      </div>

      {/* Agent cards */}
      {viewMode === 'grouped' ? (
        <div className="space-y-4">
          {categories.map(cat => (
            <AgentGroup key={cat.label} category={cat} highlightedIds={contradiction.highlightedAgentIds} />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2">
          {entries
            .sort((a, b) => b.confidence - a.confidence)
            .map(entry => (
              <AgentSignalCard
                key={entry.agentId}
                entry={entry}
                isHighlighted={contradiction.highlightedAgentIds.has(entry.agentId)}
              />
            ))}
        </div>
      )}
    </div>
  );
}
