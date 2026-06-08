/**
 * P2-1 Agent Signal Dashboard — pure helper functions.
 *
 * Computes consensus statistics, signal distribution, and per-agent
 * categorization from the raw analyst_signals data structure.
 *
 * Data contract: each agent signal is
 *   { signal: 'bullish' | 'bearish' | 'neutral', confidence: number, reasoning?: string }
 * matching backend `analyst_signals[agent_id][ticker]`.
 */

import type { AgentSignalEntry } from '@/nodes/components/agent-signal-helpers';

// ---------- Types ----------

export interface ConsensusStats {
  /** Total number of agents with signals */
  total: number;
  /** Count of bullish signals */
  bullish: number;
  /** Count of bearish signals */
  bearish: number;
  /** Count of neutral signals */
  neutral: number;
  /** Average confidence across all agents (0-100) */
  avgConfidence: number;
  /** Direction of consensus: 'bullish' | 'bearish' | 'neutral' | 'divided' */
  consensusDirection: 'bullish' | 'bearish' | 'neutral' | 'divided';
  /** Strength of consensus: ratio of dominant direction (0-1). 1.0 = unanimous */
  consensusStrength: number;
}

export interface AgentCategory {
  /** Category label */
  label: string;
  /** Agent entries in this category */
  agents: AgentSignalEntry[];
  /** Color class for UI rendering */
  colorClass: string;
  /** Badge variant */
  badgeVariant: string;
}

// ---------- Functions ----------

/**
 * Compute consensus statistics from a list of agent signal entries.
 */
export function computeConsensusStats(entries: AgentSignalEntry[]): ConsensusStats {
  const total = entries.length;
  if (total === 0) {
    return {
      total: 0,
      bullish: 0,
      bearish: 0,
      neutral: 0,
      avgConfidence: 0,
      consensusDirection: 'neutral',
      consensusStrength: 0,
    };
  }

  const bullish = entries.filter(e => e.signal === 'bullish').length;
  const bearish = entries.filter(e => e.signal === 'bearish').length;
  const neutral = entries.filter(e => e.signal === 'neutral').length;
  const avgConfidence = entries.reduce((sum, e) => sum + e.confidence, 0) / total;

  // Determine consensus direction
  const maxCount = Math.max(bullish, bearish, neutral);
  let consensusDirection: ConsensusStats['consensusDirection'];
  let consensusStrength: number;

  if (maxCount === total) {
    // Unanimous
    consensusDirection = entries[0].signal === 'neutral' ? 'neutral' : entries[0].signal;
    consensusStrength = 1.0;
  } else if (bullish === bearish && bullish > neutral) {
    consensusDirection = 'divided';
    consensusStrength = bullish / total;
  } else if (maxCount === bullish) {
    consensusDirection = 'bullish';
    consensusStrength = bullish / total;
  } else if (maxCount === bearish) {
    consensusDirection = 'bearish';
    consensusStrength = bearish / total;
  } else {
    consensusDirection = 'neutral';
    consensusStrength = neutral / total;
  }

  return { total, bullish, bearish, neutral, avgConfidence, consensusDirection, consensusStrength };
}

/**
 * Categorize agents by signal direction for grouped display.
 */
export function categorizeAgents(entries: AgentSignalEntry[]): AgentCategory[] {
  return [
    {
      label: '看多',
      agents: entries.filter(e => e.signal === 'bullish').sort((a, b) => b.confidence - a.confidence),
      colorClass: 'text-green-500',
      badgeVariant: 'success',
    },
    {
      label: '看空',
      agents: entries.filter(e => e.signal === 'bearish').sort((a, b) => b.confidence - a.confidence),
      colorClass: 'text-red-500',
      badgeVariant: 'destructive',
    },
    {
      label: '中性',
      agents: entries.filter(e => e.signal === 'neutral').sort((a, b) => b.confidence - a.confidence),
      colorClass: 'text-muted-foreground',
      badgeVariant: 'secondary',
    },
  ].filter(cat => cat.agents.length > 0);
}

/**
 * Get a human-readable consensus summary string.
 */
export function getConsensusSummary(stats: ConsensusStats): string {
  if (stats.total === 0) return '无信号数据';

  const { total, bullish, bearish, neutral, consensusDirection, consensusStrength } = stats;

  const parts: string[] = [];
  if (bullish > 0) parts.push(`${bullish} 看多`);
  if (bearish > 0) parts.push(`${bearish} 看空`);
  if (neutral > 0) parts.push(`${neutral} 中性`);

  const directionLabel: Record<string, string> = {
    bullish: '共识偏多',
    bearish: '共识偏空',
    neutral: '方向不明',
    divided: '多空分歧',
  };

  const strengthLabel = consensusStrength >= 0.8 ? '强' : consensusStrength >= 0.6 ? '中' : '弱';

  return `${parts.join(' / ')} — ${directionLabel[consensusDirection] || '待定'} (${strengthLabel}共识, ${total} agents)`;
}

/**
 * Get a color for the consensus direction (for the consensus bar).
 */
export function getConsensusColor(direction: ConsensusStats['consensusDirection']): string {
  switch (direction) {
    case 'bullish': return 'bg-green-500';
    case 'bearish': return 'bg-red-500';
    case 'neutral': return 'bg-muted-foreground';
    case 'divided': return 'bg-yellow-500';
  }
}

/**
 * Truncate reasoning text to a preview length.
 */
export function truncateReasoning(reasoning: string | undefined, maxLength: number = 80): string {
  if (!reasoning) return '';
  if (reasoning.length <= maxLength) return reasoning;
  return reasoning.slice(0, maxLength) + '...';
}
