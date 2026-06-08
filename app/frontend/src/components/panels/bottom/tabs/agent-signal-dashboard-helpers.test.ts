import { describe, expect, it } from 'vitest';

import type { AgentSignalEntry } from '@/nodes/components/agent-signal-helpers';
import {
  categorizeAgents,
  computeConsensusStats,
  getConsensusColor,
  getConsensusSummary,
  truncateReasoning,
} from './agent-signal-dashboard-helpers';

// ---------- Fixtures ----------

function makeEntry(overrides: Partial<AgentSignalEntry> & { agentId: string }): AgentSignalEntry {
  return {
    displayName: overrides.agentId,
    signal: 'neutral',
    confidence: 50,
    ...overrides,
  };
}

// ---------- Tests ----------

describe('computeConsensusStats', () => {
  it('returns zero stats for empty input', () => {
    const stats = computeConsensusStats([]);
    expect(stats).toEqual({
      total: 0,
      bullish: 0,
      bearish: 0,
      neutral: 0,
      avgConfidence: 0,
      consensusDirection: 'neutral',
      consensusStrength: 0,
    });
  });

  it('computes correct distribution for mixed signals', () => {
    const entries = [
      makeEntry({ agentId: 'a1', signal: 'bullish', confidence: 80 }),
      makeEntry({ agentId: 'a2', signal: 'bullish', confidence: 70 }),
      makeEntry({ agentId: 'a3', signal: 'bearish', confidence: 60 }),
      makeEntry({ agentId: 'a4', signal: 'neutral', confidence: 40 }),
      makeEntry({ agentId: 'a5', signal: 'neutral', confidence: 30 }),
    ];
    const stats = computeConsensusStats(entries);
    expect(stats.total).toBe(5);
    expect(stats.bullish).toBe(2);
    expect(stats.bearish).toBe(1);
    expect(stats.neutral).toBe(2);
    expect(stats.avgConfidence).toBe((80 + 70 + 60 + 40 + 30) / 5);
    expect(stats.consensusDirection).toBe('bullish'); // bullish ties neutral at 2, bullish checked first
    expect(stats.consensusStrength).toBeCloseTo(2 / 5);
  });

  it('identifies bullish consensus direction', () => {
    const entries = [
      makeEntry({ agentId: 'a1', signal: 'bullish', confidence: 80 }),
      makeEntry({ agentId: 'a2', signal: 'bullish', confidence: 70 }),
      makeEntry({ agentId: 'a3', signal: 'bullish', confidence: 60 }),
      makeEntry({ agentId: 'a4', signal: 'bearish', confidence: 50 }),
    ];
    const stats = computeConsensusStats(entries);
    expect(stats.consensusDirection).toBe('bullish');
    expect(stats.consensusStrength).toBeCloseTo(3 / 4);
  });

  it('identifies bearish consensus direction', () => {
    const entries = [
      makeEntry({ agentId: 'a1', signal: 'bearish', confidence: 90 }),
      makeEntry({ agentId: 'a2', signal: 'bearish', confidence: 80 }),
      makeEntry({ agentId: 'a3', signal: 'bullish', confidence: 50 }),
    ];
    const stats = computeConsensusStats(entries);
    expect(stats.consensusDirection).toBe('bearish');
    expect(stats.consensusStrength).toBeCloseTo(2 / 3);
  });

  it('identifies divided direction when bullish == bearish > neutral', () => {
    const entries = [
      makeEntry({ agentId: 'a1', signal: 'bullish', confidence: 80 }),
      makeEntry({ agentId: 'a2', signal: 'bullish', confidence: 70 }),
      makeEntry({ agentId: 'a3', signal: 'bearish', confidence: 85 }),
      makeEntry({ agentId: 'a4', signal: 'bearish', confidence: 75 }),
      makeEntry({ agentId: 'a5', signal: 'neutral', confidence: 30 }),
    ];
    const stats = computeConsensusStats(entries);
    expect(stats.consensusDirection).toBe('divided');
    expect(stats.bullish).toBe(2);
    expect(stats.bearish).toBe(2);
  });

  it('identifies unanimous bullish with strength 1.0', () => {
    const entries = [
      makeEntry({ agentId: 'a1', signal: 'bullish', confidence: 90 }),
      makeEntry({ agentId: 'a2', signal: 'bullish', confidence: 80 }),
    ];
    const stats = computeConsensusStats(entries);
    expect(stats.consensusDirection).toBe('bullish');
    expect(stats.consensusStrength).toBe(1.0);
  });

  it('identifies unanimous neutral', () => {
    const entries = [
      makeEntry({ agentId: 'a1', signal: 'neutral', confidence: 50 }),
      makeEntry({ agentId: 'a2', signal: 'neutral', confidence: 40 }),
    ];
    const stats = computeConsensusStats(entries);
    expect(stats.consensusDirection).toBe('neutral');
    expect(stats.consensusStrength).toBe(1.0);
  });
});

describe('categorizeAgents', () => {
  it('groups agents by signal direction, sorted by confidence desc', () => {
    const entries = [
      makeEntry({ agentId: 'a1', signal: 'bullish', confidence: 60 }),
      makeEntry({ agentId: 'a2', signal: 'bearish', confidence: 90 }),
      makeEntry({ agentId: 'a3', signal: 'bullish', confidence: 80 }),
      makeEntry({ agentId: 'a4', signal: 'neutral', confidence: 50 }),
    ];
    const categories = categorizeAgents(entries);

    // Order: 看多, 看空, 中性 (only non-empty groups)
    expect(categories).toHaveLength(3);

    // Bullish group
    expect(categories[0].label).toBe('看多');
    expect(categories[0].agents).toHaveLength(2);
    expect(categories[0].agents[0].confidence).toBe(80); // sorted desc
    expect(categories[0].agents[1].confidence).toBe(60);

    // Bearish group
    expect(categories[1].label).toBe('看空');
    expect(categories[1].agents).toHaveLength(1);
    expect(categories[1].agents[0].confidence).toBe(90);

    // Neutral group
    expect(categories[2].label).toBe('中性');
    expect(categories[2].agents).toHaveLength(1);
  });

  it('omits empty categories', () => {
    const entries = [
      makeEntry({ agentId: 'a1', signal: 'bullish', confidence: 80 }),
      makeEntry({ agentId: 'a2', signal: 'bullish', confidence: 70 }),
    ];
    const categories = categorizeAgents(entries);
    expect(categories).toHaveLength(1);
    expect(categories[0].label).toBe('看多');
  });

  it('returns empty array for empty input', () => {
    expect(categorizeAgents([])).toEqual([]);
  });
});

describe('getConsensusSummary', () => {
  it('returns "无信号数据" for zero stats', () => {
    const stats = computeConsensusStats([]);
    expect(getConsensusSummary(stats)).toBe('无信号数据');
  });

  it('formats mixed signals correctly', () => {
    const stats = computeConsensusStats([
      makeEntry({ agentId: 'a1', signal: 'bullish', confidence: 80 }),
      makeEntry({ agentId: 'a2', signal: 'bearish', confidence: 70 }),
    ]);
    const summary = getConsensusSummary(stats);
    expect(summary).toContain('1 看多');
    expect(summary).toContain('1 看空');
    expect(summary).toContain('多空分歧');
  });

  it('formats unanimous bullish with strong consensus label', () => {
    const stats = computeConsensusStats([
      makeEntry({ agentId: 'a1', signal: 'bullish', confidence: 90 }),
      makeEntry({ agentId: 'a2', signal: 'bullish', confidence: 80 }),
    ]);
    const summary = getConsensusSummary(stats);
    expect(summary).toContain('2 看多');
    expect(summary).toContain('共识偏多');
    expect(summary).toContain('强共识');
  });
});

describe('getConsensusColor', () => {
  it('returns correct color class for each direction', () => {
    expect(getConsensusColor('bullish')).toBe('bg-green-500');
    expect(getConsensusColor('bearish')).toBe('bg-red-500');
    expect(getConsensusColor('neutral')).toBe('bg-muted-foreground');
    expect(getConsensusColor('divided')).toBe('bg-yellow-500');
  });
});

describe('truncateReasoning', () => {
  it('returns empty string for undefined', () => {
    expect(truncateReasoning(undefined)).toBe('');
  });

  it('returns original text if shorter than max', () => {
    expect(truncateReasoning('short text', 100)).toBe('short text');
  });

  it('truncates and adds ellipsis', () => {
    const long = 'This is a very long reasoning text that should be truncated at the specified length limit';
    const result = truncateReasoning(long, 30);
    expect(result.length).toBe(33); // 30 + '...'
    expect(result.endsWith('...')).toBe(true);
  });
});
