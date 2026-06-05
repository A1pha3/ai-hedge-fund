/**
 * P0 1.4: BTST 决策卡 / ONE-PAGER 共享数据契约。
 *
 * 这两个视图本质上是同一份信息（`operator_summary.json` + 决策卡 + 7 份文档），
 * 但前端要"双消费入口"——一份数据，两种呈现。`BtstPanelData` 就是这份单一
 * 真相源（single source of truth）。
 *
 * 数据来源约定（按优先级）：
 *   1. 后端聚合 `btst_panel` 字段（未来）
 *   2. 前端从 `outputNodeData.btst_decision_card` + `outputNodeData.btst_one_pager` 组装
 *   3. 若两端都缺失，组件渲染"无数据"占位
 */

export type BtstAction = 'buy' | 'hold' | 'sell' | 'skip';
export type BtstEvidenceGrade = 'A' | 'B' | 'C' | 'D';
export type BtstDataQuality = 'sufficient' | 'partial' | 'insufficient';
export type BtstRiskPosture = 'aggressive' | 'standard' | 'conservative' | 'no_trade';

export interface BtstDecisionCardData {
  /** 信号日期 (YYYY-MM-DD) */
  signal_date?: string | null;
  /** 下一交易日 (YYYY-MM-DD) */
  next_trade_date?: string | null;
  /** 主票 (002463 / AAPL 等) */
  primary_ticker?: string | null;
  /** 主票名称 (可选) */
  primary_name?: string | null;
  /** 行动方向 */
  trade_bias?: BtstAction | string | null;
  /** 证据等级 */
  evidence_grade?: BtstEvidenceGrade | string | null;
  /** 数据质量 */
  data_quality?: BtstDataQuality | string | null;
  /** 风险姿态 */
  risk_posture?: BtstRiskPosture | string | null;
  /** 仓位建议 (% NAV，0-100) */
  position_scale?: number | null;
  /** 必须盘中确认的事项 */
  must_confirm?: string | null;
  /** 失效条件 */
  invalidate_if?: string | null;
  /** 早盘 / 复盘 runner 状态 */
  early_runner_status?: string | null;
}

export interface BtstOnePagerQuestion {
  /** 固定 8 个主问题的标题（与 ONE-PAGER.md 一致） */
  title: string;
  /** 单行结论 */
  answer: string;
  /** 详细解释（可选） */
  detail?: string | null;
  /** 严重度 / 状态 */
  status?: 'ok' | 'warn' | 'alert' | 'info' | string | null;
  /** 关联源文档文件名（用于"展开源文档"链接） */
  source_doc?: string | null;
}

export interface BtstOnePagerData {
  /** 信号日期 */
  signal_date?: string | null;
  /** 下一交易日 */
  next_trade_date?: string | null;
  /** 8 行主问题摘要 */
  questions: BtstOnePagerQuestion[];
  /** 顶部一句执行摘要 */
  headline?: string | null;
}

export interface BtstPanelData {
  decision_card: BtstDecisionCardData | null | undefined;
  one_pager: BtstOnePagerData | null | undefined;
}

/** 把后端字段映射成统一 view-model。容错：字段缺失则回退到 fallback。 */
export function buildBtstPanelData(outputNodeData: any): BtstPanelData {
  if (!outputNodeData || typeof outputNodeData !== 'object') {
    return { decision_card: null, one_pager: null };
  }

  // 决策卡优先读 `btst_decision_card`，缺失则从 `operator_summary` 推断
  const rawCard =
    outputNodeData.btst_decision_card ||
    outputNodeData.btst?.decision_card ||
    null;

  // ONE-PAGER 优先读 `btst_one_pager`，缺失则从 `btst.premarket_questions` 等回退
  const rawOnePager =
    outputNodeData.btst_one_pager ||
    outputNodeData.btst?.one_pager ||
    null;

  return {
    decision_card: normalizeDecisionCard(rawCard),
    one_pager: normalizeOnePager(rawOnePager),
  };
}

function normalizeDecisionCard(raw: any): BtstDecisionCardData | null {
  if (!raw || typeof raw !== 'object') return null;
  return {
    signal_date: pickStr(raw.signal_date),
    next_trade_date: pickStr(raw.next_trade_date),
    primary_ticker: pickStr(raw.primary_ticker),
    primary_name: pickStr(raw.primary_name),
    trade_bias: pickStr(raw.trade_bias) ?? 'skip',
    evidence_grade: pickStr(raw.evidence_grade),
    data_quality: pickStr(raw.data_quality),
    risk_posture: pickStr(raw.risk_posture),
    position_scale: pickNum(raw.position_scale),
    must_confirm: pickStr(raw.must_confirm),
    invalidate_if: pickStr(raw.invalidate_if),
    early_runner_status: pickStr(raw.early_runner_status),
  };
}

function normalizeOnePager(raw: any): BtstOnePagerData | null {
  if (!raw || typeof raw !== 'object') return null;

  const rawQuestions = Array.isArray(raw.questions) ? raw.questions : [];
  if (rawQuestions.length === 0 && Array.isArray(raw.lines)) {
    // 兼容形态: { lines: ["Q1: ...", "Q2: ..."] }
    return {
      signal_date: pickStr(raw.signal_date),
      next_trade_date: pickStr(raw.next_trade_date),
      headline: pickStr(raw.headline),
      questions: raw.lines
        .filter((line: unknown) => typeof line === 'string' && line.trim())
        .map((line: string) => {
          const [titlePart, ...rest] = line.split('：');
          return {
            title: titlePart?.trim() || line.trim(),
            answer: rest.join('：').trim() || '',
            status: 'info' as const,
            source_doc: null,
          };
        }),
    };
  }

  return {
    signal_date: pickStr(raw.signal_date),
    next_trade_date: pickStr(raw.next_trade_date),
    headline: pickStr(raw.headline),
    questions: rawQuestions
      .map((q: any) => {
        if (!q || typeof q !== 'object') return null;
        return {
          title: pickStr(q.title) || pickStr(q.question) || '未命名',
          answer: pickStr(q.answer) || pickStr(q.value) || '',
          detail: pickStr(q.detail) ?? null,
          status: pickStr(q.status) ?? 'info',
          source_doc: pickStr(q.source_doc) ?? null,
        } as BtstOnePagerQuestion;
      })
      .filter((q: BtstOnePagerQuestion | null): q is BtstOnePagerQuestion => q !== null),
  };
}

function pickStr(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === 'string') return v;
  return String(v);
}

function pickNum(v: unknown): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
