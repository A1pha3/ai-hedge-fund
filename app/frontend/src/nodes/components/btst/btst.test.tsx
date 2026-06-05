import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { BtstDecisionCard } from './btst-decision-card';
import { BtstDecisionCardOnePagerTabs } from './btst-decision-card-one-pager-tabs';
import { BtstOnePager } from './btst-one-pager';
import { buildBtstPanelData } from './types';

// ---------- Fixtures ----------

const fullDecisionCard = {
  signal_date: '2026-06-05',
  next_trade_date: '2026-06-08',
  primary_ticker: '002463',
  primary_name: '沪电股份',
  trade_bias: 'buy',
  evidence_grade: 'A',
  data_quality: 'sufficient',
  risk_posture: 'standard',
  position_scale: 8.5,
  must_confirm: '09:25 集合竞价需量价齐升。',
  invalidate_if: '开盘 30 分钟内跌破昨收 1%。',
  early_runner_status: 'fresh',
};

const fullOnePager = {
  signal_date: '2026-06-05',
  next_trade_date: '2026-06-08',
  headline: '市场状态中性偏多，主票 002463 推荐 BUY 8.5% NAV。',
  questions: [
    { title: '市场状态', answer: '中性偏多', status: 'ok', source_doc: 'BTST-LLM-market-state.md' },
    { title: '主票选择', answer: '002463 沪电股份', status: 'ok', source_doc: 'BTST-LLM-candidates.md' },
    { title: '早盘 runner 状态', answer: 'fresh', status: 'ok', source_doc: 'BTST-LLM-early-runner.md' },
    { title: '风控门', answer: '通过', status: 'ok', source_doc: 'BTST-LLM-risk-gate.md' },
    { title: '仓位建议', answer: '8.5% NAV', status: 'warn', detail: '受 risk_posture 影响', source_doc: 'BTST-LLM-position.md' },
    { title: '盘中必确认', answer: '量价齐升', status: 'info', source_doc: 'BTST-LLM-confirm.md' },
    { title: '失效条件', answer: '开盘跌破昨收 1%', status: 'alert', source_doc: 'BTST-LLM-invalidate.md' },
    { title: '复盘提示', answer: '对照 T+1 实际走势', status: 'info', source_doc: 'BTST-LLM-replay.md' },
  ],
};

const outputNodeDataWithBoth = {
  current_prices: { '002463': 32.5 },
  btst_decision_card: fullDecisionCard,
  btst_one_pager: fullOnePager,
};

// ---------- Tests ----------

describe('buildBtstPanelData', () => {
  it('maps backend fields into a unified BtstPanelData', () => {
    const panel = buildBtstPanelData(outputNodeDataWithBoth);
    expect(panel.decision_card?.primary_ticker).toBe('002463');
    expect(panel.decision_card?.position_scale).toBe(8.5);
    expect(panel.one_pager?.questions).toHaveLength(8);
    expect(panel.one_pager?.questions[0].title).toBe('市场状态');
  });

  it('returns nulls when neither field is present', () => {
    const panel = buildBtstPanelData({});
    expect(panel.decision_card).toBeNull();
    expect(panel.one_pager).toBeNull();
  });

  it('handles missing outputNodeData gracefully', () => {
    const panel = buildBtstPanelData(undefined);
    expect(panel.decision_card).toBeNull();
    expect(panel.one_pager).toBeNull();
  });
});

describe('BtstDecisionCard', () => {
  it('renders BUY action, primary ticker, position scale and must-confirm', () => {
    render(<BtstDecisionCard data={fullDecisionCard} currentPrice={32.5} portfolioNav={1000000} />);

    // The decision card title contains the signal date
    expect(screen.getByText(/BTST 决策卡 — 2026-06-05/)).toBeDefined();
    // Action badge says BUY (could appear as metric label too — getAllByText)
    expect(screen.getAllByText('BUY').length).toBeGreaterThan(0);
    // Primary ticker is rendered
    expect(screen.getByText('002463')).toBeDefined();
    // Position scale 8.5% NAV
    expect(screen.getByText(/8\.5% NAV/)).toBeDefined();
    // must_confirm is rendered
    expect(screen.getByText(/09:25 集合竞价需量价齐升/)).toBeDefined();
  });

  it('renders fallback UI when decision card data is null', () => {
    render(<BtstDecisionCard data={null} />);
    expect(screen.getByText(/BTST 决策卡/)).toBeDefined();
    // Explicit copy that explains the field is missing
    expect(screen.getByText(/btst_decision_card/)).toBeDefined();
  });
});

describe('BtstOnePager', () => {
  it('renders all 8 questions with status badges and expand links', () => {
    const onOpen = vi.fn();
    render(<BtstOnePager data={fullOnePager} onOpenSourceDoc={onOpen} />);

    // All 8 questions rendered
    for (const q of fullOnePager.questions) {
      expect(screen.getByText(q.title)).toBeDefined();
    }

    // OK / WARN / ALERT / INFO badges appear at least once
    expect(screen.getAllByText('OK').length).toBeGreaterThan(0);
    expect(screen.getAllByText('WARN').length).toBeGreaterThan(0);
    expect(screen.getAllByText('ALERT').length).toBeGreaterThan(0);

    // 8 source-doc links rendered
    const links = screen.getAllByRole('button', { name: /展开源文档/ });
    expect(links).toHaveLength(8);

    // Click the first link → callback fires with the doc name
    links[0].click();
    expect(onOpen).toHaveBeenCalledWith('BTST-LLM-market-state.md');
  });

  it('renders fallback UI when one-pager data is null', () => {
    render(<BtstOnePager data={null} />);
    // The CardTitle shows "BTST ONE-PAGER"
    expect(screen.getByText('BTST ONE-PAGER')).toBeDefined();
    // The fallback description text (specific to one-pager)
    expect(screen.getByText(/当前 run 未提供/)).toBeDefined();
  });
});

describe('BtstDecisionCardOnePagerTabs (P0 1.4 双重消费入口)', () => {
  it('default view is decision card; switching tabs toggles view without re-rendering data', async () => {
    const user = userEvent.setup();
    render(<BtstDecisionCardOnePagerTabs data={buildBtstPanelData(outputNodeDataWithBoth)} />);

    // Default tab: decision card visible
    const panel = screen.getByTestId('btst-panel');
    expect(panel.getAttribute('data-active-view')).toBe('decision-card');
    expect(screen.getByText(/BTST 决策卡 — 2026-06-05/)).toBeDefined();
    // ONE-PAGER CardTitle should not be visible yet (only the tab trigger text)
    // The card body uses "BTST 决策卡 — 2026-06-05" as a unique marker, so
    // confirm the one-pager card title (used in the fallback / question card) is absent.
    expect(screen.queryByText(/8 行主问题/)).toBeNull();
    expect(screen.queryByText(/当前 run 未提供/)).toBeNull();

    // Switch to ONE-PAGER
    await user.click(screen.getByTestId('btst-tab-one-pager'));
    expect(panel.getAttribute('data-active-view')).toBe('one-pager');
    // Now the one-pager card body is rendered
    expect(screen.getByText(/对照 T\+1 实际走势/)).toBeDefined();
    // The decision card heading is gone
    expect(screen.queryByText(/BTST 决策卡 — 2026-06-05/)).toBeNull();

    // Switch back
    await user.click(screen.getByTestId('btst-tab-decision-card'));
    expect(panel.getAttribute('data-active-view')).toBe('decision-card');
    expect(screen.getByText(/BTST 决策卡 — 2026-06-05/)).toBeDefined();
  });

  it('renders empty state when neither decision card nor one-pager is provided', () => {
    render(<BtstDecisionCardOnePagerTabs data={{ decision_card: null, one_pager: null }} />);
    expect(screen.getByText(/本次 run 既无/)).toBeDefined();
  });

  it('shows ONE-PAGER tab with 0-question fallback when only decision card is supplied', async () => {
    const user = userEvent.setup();
    render(
      <BtstDecisionCardOnePagerTabs
        data={{ decision_card: fullDecisionCard, one_pager: { questions: [] } }}
      />,
    );
    // Decision card visible by default
    expect(screen.getByText(/BTST 决策卡 — 2026-06-05/)).toBeDefined();
    // Switch to ONE-PAGER — should render "8 行主问题为空" fallback (questions is empty)
    await user.click(screen.getByTestId('btst-tab-one-pager'));
    expect(screen.getByText('BTST ONE-PAGER')).toBeDefined();
    // The empty-state description text
    expect(screen.getByText(/8 行主问题为空/)).toBeDefined();
  });

  it('passes the same data source to both views (no data drift between tabs)', async () => {
    const user = userEvent.setup();
    const panel = buildBtstPanelData(outputNodeDataWithBoth);
    render(<BtstDecisionCardOnePagerTabs data={panel} primaryPrice={32.5} portfolioNav={1000000} />);

    // Decision card view: 002463 / 8.5% NAV
    expect(screen.getByText('002463')).toBeDefined();
    expect(screen.getByText(/8\.5% NAV/)).toBeDefined();

    // Switch to ONE-PAGER — the 8th question (复盘提示) is rendered, confirming
    // we read from the SAME BtstPanelData instance (not a re-fetch or stale copy).
    await user.click(screen.getByTestId('btst-tab-one-pager'));
    expect(screen.getByText('BTST ONE-PAGER')).toBeDefined();
    // All 8 question titles from the source data are visible in the one-pager view
    for (const q of fullOnePager.questions) {
      expect(screen.getByText(q.title)).toBeDefined();
    }
  });
});
