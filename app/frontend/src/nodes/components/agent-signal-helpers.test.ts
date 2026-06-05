import { describe, expect, it } from 'vitest';

import {
  buildAgentSignalsForTicker,
  detectContradiction,
  sortAgentSignals,
  type AgentSignalEntry,
} from './agent-signal-helpers';

// ---------- Fixtures ----------

const AGENT_IDS = ['warren_buffett_abc123', 'charlie_munger_def456', 'ben_graham_ghi789', 'technical_analyst_jkl012'];

const DISPLAY_NAMES = new Map<string, string>([
  ['warren_buffett_abc123', 'Warren Buffett'],
  ['charlie_munger_def456', 'Charlie Munger'],
  ['ben_graham_ghi789', 'Ben Graham'],
  ['technical_analyst_jkl012', 'Technical Analyst'],
]);

function makeEntry(overrides: Partial<AgentSignalEntry> & { agentId: string }): AgentSignalEntry {
  return {
    displayName: overrides.agentId,
    signal: 'neutral',
    confidence: 50,
    ...overrides,
  };
}

function makeAnalystSignals(
  ticker: string,
  rows: Array<{ agentId: string; signal: string; confidence: number; reasoning?: string }>,
): Record<string, Record<string, unknown>> {
  const out: Record<string, Record<string, unknown>> = {};
  for (const r of rows) {
    out[r.agentId] = {
      [ticker]: {
        signal: r.signal,
        confidence: r.confidence,
        ...(r.reasoning ? { reasoning: r.reasoning } : {}),
      },
    };
  }
  return out;
}

// ---------- Tests ----------

describe('buildAgentSignalsForTicker', () => {
  it('expands analyst_signals dict into AgentSignalEntry[] for a given ticker', () => {
    const analystSignals = makeAnalystSignals('AAPL', [
      { agentId: 'warren_buffett_abc123', signal: 'bullish', confidence: 80, reasoning: 'moat' },
      { agentId: 'charlie_munger_def456', signal: 'bearish', confidence: 60 },
    ]);
    const entries = buildAgentSignalsForTicker(AGENT_IDS, DISPLAY_NAMES, analystSignals, 'AAPL');
    expect(entries).toHaveLength(2);
    expect(entries[0]).toMatchObject({
      agentId: 'warren_buffett_abc123',
      displayName: 'Warren Buffett',
      signal: 'bullish',
      confidence: 80,
      reasoning: 'moat',
    });
    expect(entries[1]).toMatchObject({
      agentId: 'charlie_munger_def456',
      displayName: 'Charlie Munger',
      signal: 'bearish',
      confidence: 60,
    });
  });

  it('skips agents with missing ticker signal and missing analyst_signals', () => {
    const partial = makeAnalystSignals('AAPL', [
      { agentId: 'warren_buffett_abc123', signal: 'bullish', confidence: 80 },
    ]);
    const entries = buildAgentSignalsForTicker(AGENT_IDS, DISPLAY_NAMES, partial, 'AAPL');
    // Other agents are either absent (charlie/ben/technical) or have no AAPL key
    expect(entries).toHaveLength(1);

    // Null / undefined inputs shouldn't crash
    const empty1 = buildAgentSignalsForTicker(AGENT_IDS, DISPLAY_NAMES, null, 'AAPL');
    const empty2 = buildAgentSignalsForTicker(AGENT_IDS, DISPLAY_NAMES, undefined, 'AAPL');
    expect(empty1).toEqual([]);
    expect(empty2).toEqual([]);
  });
});

describe('detectContradiction', () => {
  it('flags contradiction when high-confidence bullish AND bearish both exist', () => {
    const entries = [
      makeEntry({ agentId: 'a1', signal: 'bullish', confidence: 80 }),
      makeEntry({ agentId: 'a2', signal: 'bullish', confidence: 75 }),
      makeEntry({ agentId: 'a3', signal: 'bearish', confidence: 90 }),
      makeEntry({ agentId: 'a4', signal: 'bearish', confidence: 70 }),
    ];
    const result = detectContradiction(entries, { highConfidenceThreshold: 70 });
    expect(result.hasContradiction).toBe(true);
    expect(result.highConfidenceBullish).toBe(2);
    expect(result.highConfidenceBearish).toBe(2);
    // All 4 high-confidence agents are highlighted regardless of direction
    expect(result.highlightedAgentIds).toEqual(new Set(['a1', 'a2', 'a3', 'a4']));
    expect(result.summary).toMatch(/2.*看多.*2.*看空/);
  });

  it('does NOT flag contradiction when all high-confidence agents are aligned', () => {
    const entries = [
      makeEntry({ agentId: 'a1', signal: 'bullish', confidence: 90 }),
      makeEntry({ agentId: 'a2', signal: 'bullish', confidence: 80 }),
      makeEntry({ agentId: 'a3', signal: 'bearish', confidence: 40 }),
    ];
    const result = detectContradiction(entries, { highConfidenceThreshold: 70 });
    expect(result.hasContradiction).toBe(false);
    expect(result.summary).toMatch(/共识偏多|无明显矛盾/);
  });

  it('uses threshold parameter correctly (custom 50)', () => {
    const entries = [
      makeEntry({ agentId: 'a1', signal: 'bullish', confidence: 55 }),
      makeEntry({ agentId: 'a2', signal: 'bearish', confidence: 52 }),
    ];
    // Default threshold 70 → no contradiction
    expect(detectContradiction(entries).hasContradiction).toBe(false);
    // Custom threshold 50 → contradiction
    expect(detectContradiction(entries, { highConfidenceThreshold: 50 }).hasContradiction).toBe(true);
  });

  it('returns "无明显矛盾" boundary cases: empty, all-neutral, low-confidence only', () => {
    // Empty
    const r1 = detectContradiction([]);
    expect(r1.hasContradiction).toBe(false);
    expect(r1.highlightedAgentIds.size).toBe(0);
    expect(r1.summary).toMatch(/无明显矛盾/);

    // All neutral
    const r2 = detectContradiction([
      makeEntry({ agentId: 'a1', signal: 'neutral', confidence: 90 }),
      makeEntry({ agentId: 'a2', signal: 'neutral', confidence: 80 }),
    ]);
    expect(r2.hasContradiction).toBe(false);
    expect(r2.summary).toMatch(/全部中性|无明显矛盾/);

    // Directional but low confidence
    const r3 = detectContradiction([
      makeEntry({ agentId: 'a1', signal: 'bullish', confidence: 30 }),
      makeEntry({ agentId: 'a2', signal: 'bearish', confidence: 25 }),
    ]);
    expect(r3.hasContradiction).toBe(false);
    expect(r3.summary).toMatch(/无明显矛盾/);
  });
});

describe('sortAgentSignals', () => {
  const entries = [
    makeEntry({ agentId: 'a1', displayName: 'Charlie', signal: 'bearish', confidence: 70 }),
    makeEntry({ agentId: 'a2', displayName: 'Alice', signal: 'bullish', confidence: 90 }),
    makeEntry({ agentId: 'a3', displayName: 'Bob', signal: 'neutral', confidence: 50 }),
    makeEntry({ agentId: 'a4', displayName: 'Diana', signal: 'bullish', confidence: 60 }),
  ];

  it('sorts by signal (asc = bullish → neutral → bearish; desc = reversed)', () => {
    const asc = sortAgentSignals(entries, 'signal', 'asc');
    expect(asc.map(e => e.signal)).toEqual(['bullish', 'bullish', 'neutral', 'bearish']);
    // Within bullish group, higher confidence first (90 before 60)
    expect(asc.filter(e => e.signal === 'bullish').map(e => e.confidence)).toEqual([90, 60]);

    const desc = sortAgentSignals(entries, 'signal', 'desc');
    expect(desc.map(e => e.signal)).toEqual(['bearish', 'neutral', 'bullish', 'bullish']);
  });

  it('sorts by confidence (asc / desc)', () => {
    const desc = sortAgentSignals(entries, 'confidence', 'desc');
    expect(desc.map(e => e.confidence)).toEqual([90, 70, 60, 50]);

    const asc = sortAgentSignals(entries, 'confidence', 'asc');
    expect(asc.map(e => e.confidence)).toEqual([50, 60, 70, 90]);
  });

  it('sorts by displayName (locale-aware A→Z / Z→A)', () => {
    const asc = sortAgentSignals(entries, 'name', 'asc');
    expect(asc.map(e => e.displayName)).toEqual(['Alice', 'Bob', 'Charlie', 'Diana']);

    const desc = sortAgentSignals(entries, 'name', 'desc');
    expect(desc.map(e => e.displayName)).toEqual(['Diana', 'Charlie', 'Bob', 'Alice']);
  });

  it('does not mutate the input array', () => {
    const before = entries.map(e => e.agentId);
    sortAgentSignals(entries, 'confidence', 'desc');
    expect(entries.map(e => e.agentId)).toEqual(before);
  });
});

describe('end-to-end: buildAgentSignalsForTicker + detectContradiction + sortAgentSignals', () => {
  it('flags the dissenting high-confidence agent pair and highlights only them', () => {
    const analystSignals = makeAnalystSignals('AAPL', [
      // 3 high-conf bullish
      { agentId: 'warren_buffett_abc123', signal: 'bullish', confidence: 80 },
      { agentId: 'charlie_munger_def456', signal: 'bullish', confidence: 75 },
      { agentId: 'ben_graham_ghi789', signal: 'bullish', confidence: 70 },
      // 2 high-conf bearish (the "矛盾" pair)
      { agentId: 'technical_analyst_jkl012', signal: 'bearish', confidence: 85 },
    ]);

    const entries = buildAgentSignalsForTicker(AGENT_IDS, DISPLAY_NAMES, analystSignals, 'AAPL');
    expect(entries).toHaveLength(4);

    const contradiction = detectContradiction(entries, { highConfidenceThreshold: 70 });
    expect(contradiction.hasContradiction).toBe(true);
    expect(contradiction.highConfidenceBullish).toBe(3);
    expect(contradiction.highConfidenceBearish).toBe(1);
    expect(contradiction.highlightedAgentIds.size).toBe(4);

    // Sort by signal desc → bearish first, then neutral (none), then bullish
    const sorted = sortAgentSignals(entries, 'signal', 'desc');
    expect(sorted[0].signal).toBe('bearish');
    expect(sorted[sorted.length - 1].signal).toBe('bullish');
  });
});
