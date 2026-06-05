/**
 * P1 5.4 — 矛盾高亮 + agent 排序 (pure helpers)。
 *
 * 把"agent 信号 → 矛盾识别 → 排序"逻辑拆成纯函数，方便单元测试。
 * 组件层 (`InvestmentReportDialog`) 只负责"拿到结果后如何渲染"。
 *
 * 数据契约：每个 agent 的信号结构是
 *   { signal: 'bullish' | 'bearish' | 'neutral', confidence: number, reasoning?: string }
 * 与后端 `analyst_signals[agent_id][ticker]` 完全一致。
 */

export type SignalDirection = 'bullish' | 'bearish' | 'neutral';

export interface AgentSignalEntry {
  /** 节点的唯一 ID (e.g. "warren_buffett_abc123")。用于稳定 key / 高亮。 */
  agentId: string;
  /** 人类可读名 (e.g. "Warren Buffett")。UI 显示与排序 fallback 用。 */
  displayName: string;
  signal: SignalDirection;
  /** 0~100，原始 confidence 字段。 */
  confidence: number;
  /** 原始 reasoning，原样透传给上层。 */
  reasoning?: string;
}

export type AgentSortKey = 'signal' | 'confidence' | 'name';
export type AgentSortDir = 'asc' | 'desc';

export interface ContradictionOptions {
  /** 高置信度门槛。>= 该值算"高置信度" (默认 70)。 */
  highConfidenceThreshold?: number;
}

export interface ContradictionResult {
  /** 至少 1 个高置信度看多 + 1 个高置信度看空。 */
  hasContradiction: boolean;
  /** 高亮 agent id 集合 (= 高置信度多空双方 + 全部分歧来源)。 */
  highlightedAgentIds: Set<string>;
  /** 顶部摘要条文案: "3 看多 vs 2 看空" 等。 */
  summary: string;
  /** 给上层做诊断: 多空双方各自多少个高置信度。 */
  highConfidenceBullish: number;
  highConfidenceBearish: number;
}

const SIGNAL_RANK: Record<SignalDirection, number> = {
  bullish: 0,
  neutral: 1,
  bearish: 2,
};

/**
 * 把后端给的 analyst_signals 字典，展开成"按 ticker 分组的 AgentSignalEntry[]"。
 * 跳过缺失 / 非对象 / 没有 signal 字段的项 (defensive)。
 */
export function buildAgentSignalsForTicker(
  agentIds: string[],
  agentDisplayNames: Map<string, string>,
  analystSignals: Record<string, Record<string, unknown> | undefined> | null | undefined,
  ticker: string,
): AgentSignalEntry[] {
  const result: AgentSignalEntry[] = [];
  for (const agentId of agentIds) {
    const byTicker = analystSignals?.[agentId];
    const raw = byTicker?.[ticker] as { signal?: unknown; confidence?: unknown; reasoning?: unknown } | undefined;
    if (!raw || typeof raw !== 'object') continue;
    const signal = normalizeSignal(raw.signal);
    if (signal === null) continue;
    const confidence = Number.isFinite(raw.confidence) ? Number(raw.confidence) : 0;
    result.push({
      agentId,
      displayName: agentDisplayNames.get(agentId) || agentId,
      signal,
      confidence,
      reasoning: typeof raw.reasoning === 'string' ? raw.reasoning : undefined,
    });
  }
  return result;
}

/**
 * 矛盾识别：
 * 1. 过滤掉中性 (neutral) — 它们不参与"方向分歧"。
 * 2. 在剩余 agent 中，找高置信度 (>= threshold) 的看多 / 看空。
 * 3. 当且仅当 高置信度看多 >= 1 且 高置信度看空 >= 1，标记为有矛盾。
 * 4. 高亮集合 = 所有高置信度 agent (不论方向)。这样用户能一眼定位"分歧来源"。
 */
export function detectContradiction(
  entries: AgentSignalEntry[],
  options: ContradictionOptions = {},
): ContradictionResult {
  const threshold = options.highConfidenceThreshold ?? 70;

  const highConf = entries.filter(
    e => e.signal !== 'neutral' && e.confidence >= threshold,
  );
  const highConfBull = highConf.filter(e => e.signal === 'bullish');
  const highConfBear = highConf.filter(e => e.signal === 'bearish');

  const hasContradiction = highConfBull.length >= 1 && highConfBear.length >= 1;

  const highlighted = new Set<string>();
  for (const e of highConf) highlighted.add(e.agentId);

  let summary: string;
  if (hasContradiction) {
    summary = `${highConfBull.length} 高置信度看多 vs ${highConfBear.length} 高置信度看空 — 显著分歧`;
  } else if (highConf.length > 0) {
    // 全部同向 — 没有矛盾但有强信号
    const allBull = highConfBear.length === 0;
    summary = allBull
      ? `${highConfBull.length} 高置信度看多 — 共识偏多`
      : `${highConfBear.length} 高置信度看空 — 共识偏空`;
  } else {
    // 统计所有非中性 agent
    const nonNeutral = entries.filter(e => e.signal !== 'neutral');
    if (nonNeutral.length === 0) {
      summary = '无明显矛盾 (全部中性)';
    } else {
      summary = '无明显矛盾 (无高置信度反向信号)';
    }
  }

  return {
    hasContradiction,
    highlightedAgentIds: highlighted,
    summary,
    highConfidenceBullish: highConfBull.length,
    highConfidenceBearish: highConfBear.length,
  };
}

/**
 * agent 信号排序 (in-place 不必要, 永远返回新数组)。
 *
 * 排序键优先级 (按 `sortKey`):
 *   - 'signal'     → bullish (0) / neutral (1) / bearish (2)
 *   - 'confidence' → 数字大小
 *   - 'name'       → displayName 字典序 (中英文混排, localeCompare)
 *
 * 然后用 `sortDir` 决定 asc / desc。注意：
 *   - 'signal' 用 asc 排序时: bullish 排最前, bearish 排最后 (业内常用约定)。
 *   - 'confidence' 用 desc 排序时: 高置信度排最前 (默认推荐, 一眼看到重点)。
 *   - 'name' 用 asc 排序时: A→Z 字典序。
 */
export function sortAgentSignals(
  entries: AgentSignalEntry[],
  sortKey: AgentSortKey,
  sortDir: AgentSortDir,
): AgentSignalEntry[] {
  const copy = entries.slice();
  const sign = sortDir === 'asc' ? 1 : -1;

  copy.sort((a, b) => {
    if (sortKey === 'signal') {
      const diff = SIGNAL_RANK[a.signal] - SIGNAL_RANK[b.signal];
      if (diff !== 0) return sign * diff;
      // 同方向时按 confidence 降序作为二级排序 — 让高置信度排在前面
      return b.confidence - a.confidence;
    }
    if (sortKey === 'confidence') {
      return sign * (a.confidence - b.confidence);
    }
    // name
    return sign * a.displayName.localeCompare(b.displayName, undefined, { numeric: true });
  });

  return copy;
}

// ---------- internals ----------

function normalizeSignal(raw: unknown): SignalDirection | null {
  if (typeof raw !== 'string') return null;
  const v = raw.toLowerCase();
  if (v === 'bullish' || v === 'bearish' || v === 'neutral') return v;
  return null;
}
