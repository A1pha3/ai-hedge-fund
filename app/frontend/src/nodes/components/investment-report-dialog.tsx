import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { type EdgeCardData, EdgeCard } from '@/components/edge-card';
import {
  type StockHistoryExpectationData,
  ExpectationCard,
} from '@/components/expectation-card';
import { RiskMonitorPanel } from '@/components/risk-monitor-panel';
import { AdjustmentSimulator } from '@/components/adjustment-simulator';
import { BtstDecisionCardOnePagerTabs } from '@/nodes/components/btst/btst-decision-card-one-pager-tabs';
import { buildBtstPanelData } from '@/nodes/components/btst/types';
import { FactorContributionChart, type FactorContribution } from '@/nodes/components/factor-contribution-chart';
import {
  buildAgentSignalsForTicker,
  detectContradiction,
  sortAgentSignals,
  type AgentSortDir,
  type AgentSortKey,
} from '@/nodes/components/agent-signal-helpers';
import { extractBaseAgentKey } from '@/data/node-mappings';
import { createAgentDisplayNames, createHighlightedJson } from '@/utils/text-utils';
import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, Minus } from 'lucide-react';
import { useMemo, useState } from 'react';

interface InvestmentReportDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  outputNodeData: any;
  connectedAgentIds: Set<string>;
}

type ActionType = 'long' | 'short' | 'hold';
type SortKey = 'ticker' | 'edge';
type SortDir = 'asc' | 'desc';

export function InvestmentReportDialog({
  isOpen,
  onOpenChange,
  outputNodeData,
  connectedAgentIds,
}: InvestmentReportDialogProps) {
  // Hooks must be called unconditionally (React rules of hooks) — they are
  // declared up front, and the early-returns below adapt the rendered output
  // to the null-data states.

  const [sortKey, setSortKey] = useState<SortKey>('edge');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  // P1 5.4: agent 信号排序状态 (signal / confidence / name)。
  // 默认 signal desc — 看空排最前，与"快速识别分歧"的产品诉求一致。
  const [agentSortKey, setAgentSortKey] = useState<AgentSortKey>('signal');
  const [agentSortDir, setAgentSortDir] = useState<AgentSortDir>('desc');

  // P0 1.1: per-ticker edge data (may be missing if backend didn't supply it)
  // Wrap in useMemo so the empty-object fallback doesn't re-allocate every render
  // and trigger the useMemo `exhaustive-deps` warning downstream.
  const edgeData: Record<string, EdgeCardData> = useMemo(
    () => (outputNodeData?.edge_data as Record<string, EdgeCardData>) || {},
    [outputNodeData],
  );

  // P0 OPT-C: per-ticker 30-day empirical expectation (win rate / avg / worst).
  // The backend (`src.portfolio.stock_history_expectation`) is already implemented
  // and tested. When `outputNodeData.expectation_data` is provided by the backend
  // we render one ExpectationCard per ticker; otherwise we skip the section to
  // avoid implying a number that wasn't actually computed.
  const expectationData: Record<string, StockHistoryExpectationData> = useMemo(
    () =>
      (outputNodeData?.expectation_data as Record<string, StockHistoryExpectationData>) ||
      {},
    [outputNodeData],
  );
  const hasExpectationData = Object.keys(expectationData).length > 0;

  // P0 1.4: BTST 决策卡 + ONE-PAGER 共享数据 (single source of truth)。
  // 同一份 BtstPanelData 同时供给两个视图，避免双消费入口产生数据漂移。
  const btstPanel = useMemo(() => buildBtstPanelData(outputNodeData), [outputNodeData]);

  // 提取主票当日收盘价（决策卡做仓位估算用）
  const primaryTicker = btstPanel.decision_card?.primary_ticker || null;
  const primaryPrice = useMemo(() => {
    if (!primaryTicker) return null;
    const prices = (outputNodeData?.current_prices as Record<string, unknown>) || {};
    const raw = prices[primaryTicker];
    if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
    if (typeof raw === 'string') {
      const n = Number(raw);
      return Number.isFinite(n) ? n : null;
    }
    return null;
  }, [primaryTicker, outputNodeData]);

  // Sort tickers based on selected sort key + direction.
  // Default: descending by expected 30d edge (highest edge first).
  const sortedTickers = useMemo(() => {
    const tickers = Object.keys(outputNodeData?.decisions || {});
    const copy = [...tickers];
    copy.sort((a, b) => {
      if (sortKey === 'edge') {
        const aEdge = edgeData[a]?.expected_30d_edge;
        const bEdge = edgeData[b]?.expected_30d_edge;
        const aVal = aEdge === null || aEdge === undefined ? -Infinity : aEdge;
        const bVal = bEdge === null || bEdge === undefined ? -Infinity : bEdge;
        return sortDir === 'desc' ? bVal - aVal : aVal - bVal;
      }
      // ticker
      return sortDir === 'desc' ? b.localeCompare(a) : a.localeCompare(b);
    });
    return copy;
  }, [outputNodeData, sortKey, sortDir, edgeData]);

  // Use the unique node IDs directly since they're now stored as keys in analyst_signals
  const connectedUniqueAgentIds = Array.from(connectedAgentIds);
  const agents = useMemo(
    () =>
      Object.keys(outputNodeData?.analyst_signals || {}).filter(
        agent =>
          extractBaseAgentKey(agent) !== 'risk_management_agent' &&
          connectedUniqueAgentIds.includes(agent),
      ),
    [outputNodeData, connectedUniqueAgentIds],
  );

  const agentDisplayNames = useMemo(() => createAgentDisplayNames(agents), [agents]);

  // P1 5.4: 矛盾识别 (per-ticker)。summary 会在 ticker 行的迷你条/高亮用。
  // 注意: 这是纯计算, 不修改 React state, 仅 memo 缓存。
  // 必须在所有 early-return 之前调用, 遵守 React hooks 规则。
  const contradictionsByTicker = useMemo(() => {
    const out: Record<string, ReturnType<typeof detectContradiction>> = {};
    for (const ticker of Object.keys(outputNodeData?.decisions || {})) {
      const entries = buildAgentSignalsForTicker(
        agents,
        agentDisplayNames,
        outputNodeData?.analyst_signals,
        ticker,
      );
      out[ticker] = detectContradiction(entries, { highConfidenceThreshold: 70 });
    }
    return out;
  }, [outputNodeData, agents, agentDisplayNames]);

  // P1 5.4: 给定 ticker，展开为 AgentSignalEntry[]，再按用户当前排序方式排序。
  // 在 memo 之外构造, 内部读最新 state — 每次 render 都重算以反映最新排序。
  const buildSortedAgentEntries = (ticker: string) => {
    const entries = buildAgentSignalsForTicker(
      agents,
      agentDisplayNames,
      outputNodeData?.analyst_signals,
      ticker,
    );
    return sortAgentSignals(entries, agentSortKey, agentSortDir);
  };

  // Check if this is a backtest result and return early if it is
  // Backtest results should be displayed in the backtest output tab, not in the investment report dialog
  if (outputNodeData?.decisions?.backtest?.type === 'backtest_complete') {
    return null;
  }

  // Return early if no output data
  if (!outputNodeData || !outputNodeData.decisions) {
    return null;
  }

  const getActionIcon = (action: ActionType) => {
    switch (action) {
      case 'long':
        return <ArrowUp className="h-4 w-4 text-green-500" />;
      case 'short':
        return <ArrowDown className="h-4 w-4 text-red-500" />;
      case 'hold':
        return <Minus className="h-4 w-4 text-yellow-500" />;
      default:
        return null;
    }
  };

  const getSignalBadge = (signal: string) => {
    const variant = signal === 'bullish' ? 'success' :
                   signal === 'bearish' ? 'destructive' : 'outline';

    return (
      <Badge variant={variant as any}>
        {signal}
      </Badge>
    );
  };

  const getConfidenceBadge = (confidence: number) => {
    let variant = 'outline';
    if (confidence >= 50) variant = 'success';
    else if (confidence >= 0) variant = 'warning';
    else variant = 'outline';
    const rounded = Number(confidence.toFixed(1));
    return (
      <Badge variant={variant as any}>
        {rounded}%
      </Badge>
    );
  };

  // (agents / agentDisplayNames / contradictionsByTicker / buildSortedAgentEntries
  // are hoisted above the early-return; see top of component)

  const handleSortClick = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir(key === 'edge' ? 'desc' : 'asc');
    }
  };

  const sortIndicator = (key: SortKey) => {
    if (sortKey !== key) return <ArrowUpDown className="h-3 w-3 opacity-50" />;
    return sortDir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />;
  };

  // P1 5.4: agent 排序按钮的点击逻辑 (与 ticker 排序一致: 同列再点反转, 切列重置)。
  // 排序键的默认方向: confidence 走 desc (高置信度在前), 其它走 asc (与既有约定一致)。
  const handleAgentSortClick = (key: AgentSortKey) => {
    if (agentSortKey === key) {
      setAgentSortDir(agentSortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setAgentSortKey(key);
      setAgentSortDir(key === 'confidence' ? 'desc' : 'asc');
    }
  };

  // P1 5.4: 重置按钮: 把排序状态回到默认 (signal desc), 一键清空用户偏好。
  const resetAgentSort = () => {
    setAgentSortKey('signal');
    setAgentSortDir('desc');
  };

  const agentSortIndicator = (key: AgentSortKey) => {
    if (agentSortKey !== key) return <ArrowUpDown className="h-3 w-3 opacity-50" />;
    return agentSortDir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />;
  };

  // P0 1.1: compute a one-line summary when the backend didn't supply one.
  const buildFallbackSummary = (edge: number | null | undefined): string => {
    if (edge === null || edge === undefined) {
      return '等待回测/实盘数据补全 edge 字段。';
    }
    if (edge > 5) {
      return `30 天期望收益 ${edge.toFixed(2)}% 处于前列，可重点关注。`;
    }
    if (edge > 0) {
      return `30 天期望收益 ${edge.toFixed(2)}% 偏正，仓位建议保守。`;
    }
    return `30 天期望收益 ${edge.toFixed(2)}% 为负，谨慎开仓。`;
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-6xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold">Investment Report</DialogTitle>
          <DialogDescription>
            20 个 agent 的多空信号 / 30 天期望收益 / 矛盾高亮 — 盘前 30 秒定位分歧。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-8 my-4">
          {/* P0 1.4: BTST 决策卡 / ONE-PAGER 双重消费入口 (S) — DONE 2026-06-05 */}
          {(btstPanel.decision_card || btstPanel.one_pager) && (
            <section data-testid="btst-section">
              <BtstDecisionCardOnePagerTabs
                data={btstPanel}
                primaryPrice={primaryPrice}
              />
            </section>
          )}

          {/* P1 1.5: Risk Monitor Panel — HHI / CVaR / Short Ratio / Exposure bars */}
          <section data-testid="risk-monitor-section">
            <RiskMonitorPanel riskMetrics={outputNodeData?.risk_metrics} />
          </section>

          {/* P2 2.3: Adjustment Simulator — "cancel / reduce" one-click pre-trade checks */}
          {sortedTickers.length > 0 && (
            <section data-testid="adjustment-simulator-section">
              <h2 className="text-lg font-semibold mb-2">Pre-Trade Simulator</h2>
              <p className="text-sm text-muted-foreground mb-4">
                模拟取消 / 减仓对组合风险的影响 — 仅模拟, 不实际下单。
              </p>
              <AdjustmentSimulator
                decisions={outputNodeData?.decisions || {}}
                positions={outputNodeData?.final_portfolio?.positions || {}}
                currentPrices={outputNodeData?.current_prices || {}}
                cash={outputNodeData?.final_portfolio?.cash || 0}
              />
            </section>
          )}

          {/* Summary Section */}
          <section>
            <h2 className="text-lg font-semibold mb-4">Summary</h2>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>
                  Recommended trading actions based on analyst signals
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-1 text-xs font-semibold"
                          onClick={() => handleSortClick('ticker')}
                        >
                          Ticker
                          {sortIndicator('ticker')}
                        </Button>
                      </TableHead>
                      <TableHead>Price</TableHead>
                      <TableHead>Action</TableHead>
                      <TableHead>Quantity</TableHead>
                      <TableHead>Confidence</TableHead>
                      <TableHead>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-1 text-xs font-semibold"
                          onClick={() => handleSortClick('edge')}
                        >
                          30D Edge
                          {sortIndicator('edge')}
                        </Button>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sortedTickers.map(ticker => {
                      const decision = outputNodeData.decisions[ticker];
                      const currentPrice = outputNodeData.current_prices?.[ticker] || 'N/A';
                      const edge = edgeData[ticker]?.expected_30d_edge;
                      return (
                        <TableRow key={ticker}>
                          <TableCell className="font-medium">{ticker}</TableCell>
                          <TableCell>${typeof currentPrice === 'number' ? currentPrice.toFixed(2) : currentPrice}</TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              {getActionIcon(decision.action as ActionType)}
                              <span className="capitalize">{decision.action}</span>
                            </div>
                          </TableCell>
                          <TableCell>{decision.quantity}</TableCell>
                          <TableCell>{getConfidenceBadge(decision.confidence)}</TableCell>
                          <TableCell>
                            {edge !== null && edge !== undefined ? (
                              <span className={edge > 0 ? 'text-green-500 font-semibold' : edge < 0 ? 'text-red-500 font-semibold' : ''}>
                                {edge > 0 ? '+' : ''}{edge.toFixed(2)}%
                              </span>
                            ) : (
                              <span className="text-muted-foreground">--</span>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </section>

          {/* 30D Edge Cards (P0 1.1) — one card per ticker */}
          {sortedTickers.length > 0 && (
            <section>
              <h2 className="text-lg font-semibold mb-4">30D Edge Cards</h2>
              <p className="text-sm text-muted-foreground mb-4">
                未来 30 天期望收益 / 风险敞口 / 风险预算 — 盘前 30 秒内一眼看穿"哪只票最该买、还能下多少"。
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {sortedTickers.map(ticker => {
                  const existing = edgeData[ticker];
                  const cardData: EdgeCardData = {
                    expected_30d_edge: existing?.expected_30d_edge ?? null,
                    cvar_95: existing?.cvar_95 ?? null,
                    risk_budget_ratio: existing?.risk_budget_ratio ?? null,
                    edge_summary: existing?.edge_summary ?? buildFallbackSummary(existing?.expected_30d_edge),
                  };
                  return (
                    <EdgeCard
                      key={ticker}
                      ticker={ticker}
                      data={cardData}
                    />
                  );
                })}
              </div>
            </section>
          )}

          {/* P0 OPT-C: 30-Day Expectation Cards (empirical win rate / avg / worst).
              Renders only when the backend supplied `expectation_data`. Each card
              shows the historical win rate and best/worst/avg 30-day return for
              the strategy, with a small-sample warning when n < 5. */}
          {hasExpectationData && (
            <section data-testid="expectation-section">
              <h2 className="text-lg font-semibold mb-4">30D Empirical Expectation</h2>
              <p className="text-sm text-muted-foreground mb-4">
                过去 60 日内该票在当前策略下的历史实证 ——
                胜率、期望收益、最坏 / 最好表现。样本 &lt; 5 时仅作参考。
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {sortedTickers
                  .filter(ticker => expectationData[ticker] !== undefined)
                  .map(ticker => (
                    <ExpectationCard
                      key={ticker}
                      data={expectationData[ticker]}
                    />
                  ))}
              </div>
            </section>
          )}

          {/* Analyst Signals Section */}
          <section>
            <h2 className="text-lg font-semibold mb-4">Analyst Signals</h2>

            {/* P1 5.4: 矛盾摘要条 — 当且仅当存在矛盾 ticker 时渲染。醒目但不刺眼：amber-500 边框 + 浅 amber 底。 */}
            {(() => {
              const flagged = sortedTickers.filter(
                t => contradictionsByTicker[t]?.hasContradiction,
              );
              if (flagged.length === 0) {
                return (
                  <div
                    data-testid="contradiction-banner-no-conflict"
                    className="mb-4 rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-sm text-muted-foreground"
                  >
                    无明显矛盾 — 所有 ticker 的高置信度 agent 方向一致。
                  </div>
                );
              }
              return (
                <div
                  data-testid="contradiction-banner"
                  className="mb-4 flex items-start gap-2 rounded-md border border-amber-500/60 bg-amber-50 dark:bg-amber-950/30 px-3 py-2 text-sm"
                >
                  <AlertTriangle className="h-4 w-4 mt-0.5 text-amber-600 dark:text-amber-400 shrink-0" />
                  <div className="flex-1">
                    <div className="font-medium text-amber-800 dark:text-amber-300">
                      检测到 {flagged.length} 只 ticker 存在高置信度分歧
                    </div>
                    <ul className="mt-1 text-xs text-amber-700 dark:text-amber-400/90 space-y-0.5">
                      {flagged.map(t => (
                        <li key={t}>
                          <span className="font-mono font-semibold">{t}</span>: {contradictionsByTicker[t].summary}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              );
            })()}

            {/* P1 5.4: agent 排序工具条 — 与 Summary 表头一致风格: ghost 按钮 + 排序图标 + reset 入口。 */}
            <div
              data-testid="agent-sort-toolbar"
              className="flex items-center justify-between mb-2 gap-2 flex-wrap"
            >
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <span>按</span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-xs"
                  data-testid="agent-sort-signal"
                  onClick={() => handleAgentSortClick('signal')}
                >
                  方向 {agentSortIndicator('signal')}
                </Button>
                <span>/</span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-xs"
                  data-testid="agent-sort-confidence"
                  onClick={() => handleAgentSortClick('confidence')}
                >
                  置信度 {agentSortIndicator('confidence')}
                </Button>
                <span>/</span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-xs"
                  data-testid="agent-sort-name"
                  onClick={() => handleAgentSortClick('name')}
                >
                  名称 {agentSortIndicator('name')}
                </Button>
              </div>
              <Button
                variant="outline"
                size="sm"
                className="h-6 px-2 text-xs"
                data-testid="agent-sort-reset"
                onClick={resetAgentSort}
              >
                重置排序
              </Button>
            </div>

            <Accordion type="multiple" className="w-full">
              {sortedTickers.map(ticker => {
                const contradiction = contradictionsByTicker[ticker];
                const sortedEntries = buildSortedAgentEntries(ticker);
                const totalCount = sortedEntries.length || 1;
                const bullCount = sortedEntries.filter(e => e.signal === 'bullish').length;
                const neutralCount = sortedEntries.filter(e => e.signal === 'neutral').length;
                const bearCount = sortedEntries.filter(e => e.signal === 'bearish').length;

                return (
                  <AccordionItem
                    key={ticker}
                    value={ticker}
                    data-testid={`analyst-accordion-item-${ticker}`}
                    className={
                      contradiction?.hasContradiction
                        ? 'border-amber-500/60 border-2 rounded-md mb-2'
                        : undefined
                    }
                  >
                    <AccordionTrigger className="text-base font-medium px-4 py-3 bg-muted/30 rounded-md hover:bg-muted/50">
                      <div className="flex items-center gap-3 flex-1">
                        <div className="flex items-center gap-2">
                          {ticker}
                          <div className="flex items-center gap-1">
                            {getActionIcon(outputNodeData.decisions[ticker].action as ActionType)}
                            <span className="text-sm font-normal text-muted-foreground">
                              {outputNodeData.decisions[ticker].action} {outputNodeData.decisions[ticker].quantity} shares
                            </span>
                          </div>
                        </div>
                        {/* P1 5.4: mini 分布条 (绿/灰/红 三色比例)。宽度按人数比例。 */}
                        {sortedEntries.length > 0 && (
                          <div
                            data-testid={`signal-distribution-${ticker}`}
                            className="flex h-2 w-32 rounded-full overflow-hidden bg-muted"
                            title={`多 ${bullCount} / 中 ${neutralCount} / 空 ${bearCount}`}
                          >
                            {bullCount > 0 && (
                              <div
                                className="bg-green-500"
                                style={{ width: `${(bullCount / totalCount) * 100}%` }}
                                data-testid={`dist-bull-${ticker}`}
                              />
                            )}
                            {neutralCount > 0 && (
                              <div
                                className="bg-gray-400"
                                style={{ width: `${(neutralCount / totalCount) * 100}%` }}
                                data-testid={`dist-neutral-${ticker}`}
                              />
                            )}
                            {bearCount > 0 && (
                              <div
                                className="bg-red-500"
                                style={{ width: `${(bearCount / totalCount) * 100}%` }}
                                data-testid={`dist-bear-${ticker}`}
                              />
                            )}
                          </div>
                        )}
                        {contradiction?.hasContradiction && (
                          <Badge
                            variant="outline"
                            data-testid={`contradiction-flag-${ticker}`}
                            className="border-amber-500/60 text-amber-700 dark:text-amber-400 text-[10px] px-1.5 py-0"
                          >
                            矛盾
                          </Badge>
                        )}
                      </div>
                    </AccordionTrigger>
                    <AccordionContent className="pt-4 px-1">
                      <div className="space-y-4">
                        {/* Per-ticker Edge card inline summary (P0 1.1) */}
                        {edgeData[ticker] && (
                          <div className="rounded-md border border-border/60 bg-muted/20 p-3 text-sm">
                            <span className="font-medium text-foreground">30D Edge: </span>
                            <span className={
                              (edgeData[ticker].expected_30d_edge ?? 0) > 0
                                ? 'text-green-500 font-semibold'
                                : (edgeData[ticker].expected_30d_edge ?? 0) < 0
                                  ? 'text-red-500 font-semibold'
                                  : 'text-muted-foreground'
                            }>
                              {edgeData[ticker].expected_30d_edge !== null && edgeData[ticker].expected_30d_edge !== undefined
                                ? `${edgeData[ticker].expected_30d_edge! > 0 ? '+' : ''}${edgeData[ticker].expected_30d_edge!.toFixed(2)}%`
                                : '--'}
                            </span>
                            {edgeData[ticker].risk_budget_ratio !== null && edgeData[ticker].risk_budget_ratio !== undefined && (
                              <span className="ml-3 text-muted-foreground">
                                Risk Budget: {(edgeData[ticker].risk_budget_ratio! * 100).toFixed(0)}%
                              </span>
                            )}
                          </div>
                        )}
                        {/* P1 1.2: Layer B/C factor contribution chart — fusion weights visualized.
                            Data sources (checked in order):
                              1. outputNodeData.factor_contributions[ticker] — backend-sent per-ticker factor data
                              2. outputNodeData.layer_b_summaries[ticker].top_factors — alternative path
                        */}
                        {(() => {
                          const fc = outputNodeData?.factor_contributions as Record<string, FactorContribution[]> | undefined;
                          const lbs = outputNodeData?.layer_b_summaries as Record<string, { top_factors?: FactorContribution[] }> | undefined;
                          const factors = fc?.[ticker] || lbs?.[ticker]?.top_factors;
                          if (!factors || factors.length === 0) return null;
                          return (
                            <FactorContributionChart
                              factors={factors}
                              title={`Factor Contributions — ${ticker}`}
                            />
                          );
                        })()}
                        {/* Agent Signals — P1 5.4: 用排序后的 entries 替代原 agents 列表; 矛盾高亮用 amber ring。 */}
                        <div className="grid grid-cols-1 gap-4">
                          {sortedEntries.map(entry => {
                            const signal = outputNodeData.analyst_signals[entry.agentId]?.[ticker];
                            const isHighlighted = contradiction?.highlightedAgentIds.has(entry.agentId);
                            return (
                              <Card
                                key={entry.agentId}
                                data-testid={`agent-card-${entry.agentId}-${ticker}`}
                                data-highlighted={isHighlighted ? 'true' : 'false'}
                                className={
                                  isHighlighted
                                    ? 'overflow-hidden border-amber-500/60 ring-2 ring-amber-500/40'
                                    : 'overflow-hidden'
                                }
                              >
                                <CardHeader className="bg-muted/50 pb-3">
                                  <div className="flex items-center justify-between">
                                    <CardTitle className="text-base">
                                      {entry.displayName}
                                    </CardTitle>
                                    <div className="flex items-center gap-2">
                                      {getSignalBadge(entry.signal)}
                                      {getConfidenceBadge(entry.confidence)}
                                    </div>
                                  </div>
                                </CardHeader>
                                <CardContent className="pt-3">
                                  {signal && typeof signal.reasoning === 'string' ? (
                                    <p className="text-sm whitespace-pre-line">
                                      {signal.reasoning}
                                    </p>
                                  ) : signal ? (
                                    <div className="max-h-48 overflow-y-auto bg-muted/30">
                                      <pre
                                        className="whitespace-pre-wrap break-words rounded-md bg-[#1e1e1e] p-3 text-sm leading-relaxed text-[#d4d4d4]"
                                        dangerouslySetInnerHTML={{ __html: createHighlightedJson(JSON.stringify(signal.reasoning, null, 2)) }}
                                      />
                                    </div>
                                  ) : null}
                                </CardContent>
                              </Card>
                            );
                          })}
                        </div>
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                );
              })}
            </Accordion>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
