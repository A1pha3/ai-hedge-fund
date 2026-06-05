import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { InvestmentReportDialog } from './investment-report-dialog';

// ---------- Fixtures ----------

const AGENT_IDS = [
  'warren_buffett_abc123',
  'charlie_munger_def456',
  'ben_graham_ghi789',
  'technical_analyst_jkl012',
];

function makeOutputNodeData(opts: {
  /**
   *  ticker → 各 agent 的 {signal, confidence}。
   *  AAPL: 3 高置信度看多 + 1 高置信度看空 → 矛盾
   *  MSFT: 全部看多              → 无矛盾
   *  TSLA: 无信号                → 无 agent card
   */
  tickerSignals: Record<string, Record<string, { signal: string; confidence: number }>>;
  includeTickerWithoutSignals?: boolean;
}) {
  const analystSignals: Record<string, Record<string, unknown>> = {};
  for (const agent of AGENT_IDS) {
    analystSignals[agent] = {};
    for (const [ticker, byAgent] of Object.entries(opts.tickerSignals)) {
      if (byAgent[agent]) {
        analystSignals[agent][ticker] = {
          signal: byAgent[agent].signal,
          confidence: byAgent[agent].confidence,
          reasoning: `${agent} on ${ticker}: ${byAgent[agent].signal} at ${byAgent[agent].confidence}%`,
        };
      }
    }
  }

  const decisions: Record<string, { action: string; quantity: number; confidence: number }> = {};
  for (const ticker of Object.keys(opts.tickerSignals)) {
    decisions[ticker] = { action: 'long', quantity: 100, confidence: 70 };
  }
  if (opts.includeTickerWithoutSignals) {
    decisions.TSLA = { action: 'short', quantity: 50, confidence: 40 };
  }

  return {
    decisions,
    analyst_signals: analystSignals,
    current_prices: { AAPL: 150, MSFT: 300 },
  };
}

// ---------- Tests ----------

describe('InvestmentReportDialog — P1 5.4 contradiction highlighting + agent sorting', () => {
  it('shows the amber contradiction banner when high-confidence bullish AND bearish agents disagree', async () => {
    const user = userEvent.setup();
    const data = makeOutputNodeData({
      tickerSignals: {
        AAPL: {
          warren_buffett_abc123: { signal: 'bullish', confidence: 85 },
          charlie_munger_def456: { signal: 'bullish', confidence: 80 },
          ben_graham_ghi789: { signal: 'bullish', confidence: 75 },
          technical_analyst_jkl012: { signal: 'bearish', confidence: 90 },
        },
        MSFT: {
          warren_buffett_abc123: { signal: 'bullish', confidence: 80 },
          charlie_munger_def456: { signal: 'bullish', confidence: 75 },
          ben_graham_ghi789: { signal: 'bullish', confidence: 70 },
        },
      },
    });

    render(
      <InvestmentReportDialog
        isOpen={true}
        onOpenChange={() => {}}
        outputNodeData={data}
        connectedAgentIds={new Set(AGENT_IDS)}
      />,
    );

    // 1) Banner exists
    const banner = screen.getByTestId('contradiction-banner');
    expect(banner).toBeDefined();
    expect(banner.textContent).toMatch(/AAPL/);
    expect(banner.textContent).toMatch(/3.*看多.*1.*看空|3.*vs.*1/);

    // 2) AAPL AccordionItem is amber-flagged
    const aaplItem = screen.getByTestId('analyst-accordion-item-AAPL');
    expect(aaplItem.className).toMatch(/amber/);
    expect(screen.getByTestId('contradiction-flag-AAPL')).toBeDefined();

    // 3) MSFT has no contradiction
    expect(screen.queryByTestId('contradiction-flag-MSFT')).toBeNull();

    // 4) Expand the AAPL accordion so its agent cards become visible,
    //    then check that all 4 high-confidence agents are highlighted.
    await user.click(screen.getByRole('button', { name: /AAPL/ }));
    const aaplCards = screen.getAllByTestId(/^agent-card-.*-AAPL$/);
    expect(aaplCards).toHaveLength(4);
    for (const card of aaplCards) {
      expect(card.getAttribute('data-highlighted')).toBe('true');
    }
  });

  it('shows "无明显矛盾" empty state when no ticker has a contradiction', () => {
    const data = makeOutputNodeData({
      tickerSignals: {
        MSFT: {
          warren_buffett_abc123: { signal: 'bullish', confidence: 80 },
          charlie_munger_def456: { signal: 'bullish', confidence: 75 },
          ben_graham_ghi789: { signal: 'neutral', confidence: 60 },
        },
      },
    });

    render(
      <InvestmentReportDialog
        isOpen={true}
        onOpenChange={() => {}}
        outputNodeData={data}
        connectedAgentIds={new Set(AGENT_IDS)}
      />,
    );

    expect(screen.getByTestId('contradiction-banner-no-conflict')).toBeDefined();
    expect(screen.queryByTestId('contradiction-banner')).toBeNull();
  });

  it('agent sort buttons reorder agent cards and the reset button restores the default', async () => {
    const user = userEvent.setup();
    const data = makeOutputNodeData({
      tickerSignals: {
        AAPL: {
          warren_buffett_abc123: { signal: 'bearish', confidence: 70 },
          charlie_munger_def456: { signal: 'bullish', confidence: 90 },
          ben_graham_ghi789: { signal: 'neutral', confidence: 50 },
        },
      },
    });

    render(
      <InvestmentReportDialog
        isOpen={true}
        onOpenChange={() => {}}
        outputNodeData={data}
        connectedAgentIds={new Set(AGENT_IDS)}
      />,
    );

    // Expand the AAPL accordion so its agent cards become visible.
    // The trigger is the button that contains the ticker name.
    const aaplTrigger = screen.getByRole('button', { name: /AAPL/ });
    await user.click(aaplTrigger);

    // Default: signal desc → bearish first (rank 2, "矛盾 first" UX),
    //          then neutral, then bullish.
    const cards = () =>
      screen.getAllByTestId(/^agent-card-.*-AAPL$/).map(c =>
        c.getAttribute('data-testid'),
      );
    expect(cards()[0]).toMatch(/warren_buffett/); // bearish (rank 2)
    expect(cards()[1]).toMatch(/ben_graham/); // neutral (rank 1)
    expect(cards()[2]).toMatch(/charlie_munger/); // bullish (rank 0)

    // Click "置信度" → desc → 90 first
    await user.click(screen.getByTestId('agent-sort-confidence'));
    expect(cards()[0]).toMatch(/charlie_munger/);
    expect(cards()[cards().length - 1]).toMatch(/ben_graham/);

    // Click "名称" → asc → ben_graham < charlie_munger < warren_buffett
    await user.click(screen.getByTestId('agent-sort-name'));
    expect(cards()[0]).toMatch(/ben_graham/);
    expect(cards()[cards().length - 1]).toMatch(/warren_buffett/);

    // Reset → back to signal desc default
    await user.click(screen.getByTestId('agent-sort-reset'));
    expect(cards()[0]).toMatch(/warren_buffett/);
    expect(cards()[1]).toMatch(/ben_graham/);
  });

  it('renders the mini distribution bar (bull/neutral/bear) in each ticker accordion', () => {
    const data = makeOutputNodeData({
      tickerSignals: {
        AAPL: {
          warren_buffett_abc123: { signal: 'bullish', confidence: 80 },
          charlie_munger_def456: { signal: 'bullish', confidence: 75 },
          ben_graham_ghi789: { signal: 'bearish', confidence: 70 },
        },
      },
    });

    render(
      <InvestmentReportDialog
        isOpen={true}
        onOpenChange={() => {}}
        outputNodeData={data}
        connectedAgentIds={new Set(AGENT_IDS)}
      />,
    );

    const distribution = screen.getByTestId('signal-distribution-AAPL');
    expect(distribution).toBeDefined();
    expect(within(distribution).getByTestId('dist-bull-AAPL')).toBeDefined();
    expect(within(distribution).getByTestId('dist-bear-AAPL')).toBeDefined();
    // No neutral in this fixture
    expect(within(distribution).queryByTestId('dist-neutral-AAPL')).toBeNull();
  });

  it('boundary: ticker with no agent signals renders gracefully (no banner, no crash)', () => {
    const data = makeOutputNodeData({
      tickerSignals: { AAPL: {} }, // no agent signals for AAPL
      includeTickerWithoutSignals: true,
    });

    // Should not throw
    render(
      <InvestmentReportDialog
        isOpen={true}
        onOpenChange={() => {}}
        outputNodeData={data}
        connectedAgentIds={new Set(AGENT_IDS)}
      />,
    );

    // AAPL still appears but no agent cards / distribution
    expect(screen.getByTestId('analyst-accordion-item-AAPL')).toBeDefined();
    expect(screen.queryByTestId('signal-distribution-AAPL')).toBeNull();
    // No contradiction banner — falls into the "无明显矛盾" empty state
    expect(screen.getByTestId('contradiction-banner-no-conflict')).toBeDefined();
  });
});
