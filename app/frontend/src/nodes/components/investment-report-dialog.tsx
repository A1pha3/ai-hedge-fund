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
import { BtstDecisionCardOnePagerTabs } from '@/nodes/components/btst/btst-decision-card-one-pager-tabs';
import { buildBtstPanelData } from '@/nodes/components/btst/types';
import { extractBaseAgentKey } from '@/data/node-mappings';
import { createAgentDisplayNames, createHighlightedJson } from '@/utils/text-utils';
import { ArrowDown, ArrowUp, ArrowUpDown, Minus } from 'lucide-react';
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

  // P0 1.1: per-ticker edge data (may be missing if backend didn't supply it)
  // Wrap in useMemo so the empty-object fallback doesn't re-allocate every render
  // and trigger the useMemo `exhaustive-deps` warning downstream.
  const edgeData: Record<string, EdgeCardData> = useMemo(
    () => (outputNodeData?.edge_data as Record<string, EdgeCardData>) || {},
    [outputNodeData],
  );

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

  // Use the unique node IDs directly since they're now stored as keys in analyst_signals
  const connectedUniqueAgentIds = Array.from(connectedAgentIds);
  const agents = Object.keys(outputNodeData.analyst_signals || {})
    .filter(agent =>
      extractBaseAgentKey(agent) !== 'risk_management_agent' && connectedUniqueAgentIds.includes(agent)
    );

  const agentDisplayNames = createAgentDisplayNames(agents);

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

          {/* Analyst Signals Section */}
          <section>
            <h2 className="text-lg font-semibold mb-4">Analyst Signals</h2>
            <Accordion type="multiple" className="w-full">
              {sortedTickers.map(ticker => (
                <AccordionItem key={ticker} value={ticker}>
                  <AccordionTrigger className="text-base font-medium px-4 py-3 bg-muted/30 rounded-md hover:bg-muted/50">
                    <div className="flex items-center gap-2">
                      {ticker}
                      <div className="flex items-center gap-1">
                        {getActionIcon(outputNodeData.decisions[ticker].action as ActionType)}
                        <span className="text-sm font-normal text-muted-foreground">
                          {outputNodeData.decisions[ticker].action} {outputNodeData.decisions[ticker].quantity} shares
                        </span>
                      </div>
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
                      {/* Agent Signals */}
                      <div className="grid grid-cols-1 gap-4">
                        {agents.map(agent => {
                          const signal = outputNodeData.analyst_signals[agent]?.[ticker];
                          if (!signal) return null;

                          return (
                            <Card key={agent} className="overflow-hidden">
                              <CardHeader className="bg-muted/50 pb-3">
                                <div className="flex items-center justify-between">
                                  <CardTitle className="text-base">
                                    {agentDisplayNames.get(agent) || agent}
                                  </CardTitle>
                                  <div className="flex items-center gap-2">
                                    {getSignalBadge(signal.signal)}
                                    {getConfidenceBadge(signal.confidence)}
                                  </div>
                                </div>
                              </CardHeader>
                              <CardContent className="pt-3">
                                {typeof signal.reasoning === 'string' ? (
                                  <p className="text-sm whitespace-pre-line">
                                    {signal.reasoning}
                                  </p>
                                ) : (
                                  <div className="max-h-48 overflow-y-auto bg-muted/30">
                                    <pre
                                      className="whitespace-pre-wrap break-words rounded-md bg-[#1e1e1e] p-3 text-sm leading-relaxed text-[#d4d4d4]"
                                      dangerouslySetInnerHTML={{ __html: createHighlightedJson(JSON.stringify(signal.reasoning, null, 2)) }}
                                    />
                                  </div>
                                )}
                              </CardContent>
                            </Card>
                          );
                        })}
                      </div>
                    </div>
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
