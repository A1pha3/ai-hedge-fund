import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { AgentNodeData, OutputNodeData, PortfolioPositionData } from '@/contexts/node-context';
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import type { BacktestPerformanceMetrics } from '@/services/types';
import { MoreHorizontal } from 'lucide-react';
import { BacktestEquityCurve } from '@/components/backtest-equity-curve';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { getActionColor } from './output-tab-utils';

type AgentDataMap = Record<string, AgentNodeData>;

interface BacktestTickerDetail {
  ticker: string;
  action?: string;
  quantity?: number;
  price?: number;
  shares_owned?: number;
  long_shares?: number;
  short_shares?: number;
  position_value?: number;
  bullish_count?: number;
  bearish_count?: number;
  neutral_count?: number;
}

interface BacktestPeriod {
  date: string;
  portfolio_value: number;
  cash: number;
  portfolio_return?: number;
  performance_metrics?: BacktestPerformanceMetrics;
  ticker_details?: BacktestTickerDetail[];
  long_short_ratio?: number | null;
}

type ActivityRow =
  | {
      type: 'ticker';
      date: string;
      ticker: string;
      action?: string;
      quantity?: number;
      price?: number;
      shares_owned?: number;
      long_shares?: number;
      short_shares?: number;
      position_value?: number;
      bullish_count?: number;
      bearish_count?: number;
      neutral_count?: number;
    }
  | {
      type: 'summary';
      date: string;
      portfolio_value: number;
      cash: number;
      portfolio_return?: number;
      total_position_value: number;
      performance_metrics?: BacktestPerformanceMetrics;
    };

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
}

function asBacktestTickerDetail(value: unknown): BacktestTickerDetail | null {
  const record = asRecord(value);
  if (!record || typeof record.ticker !== 'string') {
    return null;
  }
  return {
    ticker: record.ticker,
    action: typeof record.action === 'string' ? record.action : undefined,
    quantity: typeof record.quantity === 'number' ? record.quantity : undefined,
    price: typeof record.price === 'number' ? record.price : undefined,
    shares_owned: typeof record.shares_owned === 'number' ? record.shares_owned : undefined,
    long_shares: typeof record.long_shares === 'number' ? record.long_shares : undefined,
    short_shares: typeof record.short_shares === 'number' ? record.short_shares : undefined,
    position_value: typeof record.position_value === 'number' ? record.position_value : undefined,
    bullish_count: typeof record.bullish_count === 'number' ? record.bullish_count : undefined,
    bearish_count: typeof record.bearish_count === 'number' ? record.bearish_count : undefined,
    neutral_count: typeof record.neutral_count === 'number' ? record.neutral_count : undefined,
  };
}

function asBacktestPeriod(value: unknown): BacktestPeriod | null {
  const record = asRecord(value);
  if (!record || typeof record.date !== 'string' || typeof record.portfolio_value !== 'number') {
    return null;
  }

  const tickerDetails = Array.isArray(record.ticker_details)
    ? record.ticker_details
        .map(asBacktestTickerDetail)
        .filter((detail): detail is BacktestTickerDetail => detail !== null)
    : undefined;

  return {
    date: record.date,
    portfolio_value: record.portfolio_value,
    cash: typeof record.cash === 'number' ? record.cash : 0,
    portfolio_return: typeof record.portfolio_return === 'number' ? record.portfolio_return : undefined,
    performance_metrics: asRecord(record.performance_metrics) as BacktestPerformanceMetrics | undefined,
    ticker_details: tickerDetails,
    long_short_ratio: typeof record.long_short_ratio === 'number' || record.long_short_ratio === null ? record.long_short_ratio : undefined,
  };
}

function getBacktestPeriods(agentData: AgentDataMap): BacktestPeriod[] {
  const rawResults = agentData['backtest']?.backtestResults;
  if (!Array.isArray(rawResults)) {
    return [];
  }

  return rawResults
    .map(asBacktestPeriod)
    .filter((period): period is BacktestPeriod => period !== null);
}

// Component for displaying backtest progress
function BacktestProgress({ agentData }: { agentData: AgentDataMap }) {
  const backtestAgent = agentData['backtest'];
  
  if (!backtestAgent) return null;
  
  return (
    <Card className="bg-transparent mb-4">
      <CardHeader>
        <CardTitle className="text-lg">Backtest Progress</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {/* Current Status */}
          <div className="flex items-center gap-2">
            <MoreHorizontal className="h-4 w-4 text-yellow-500" />
            <span className="font-medium">Backtest Runner</span>
            <span className="text-yellow-500 flex-1">{backtestAgent.message || backtestAgent.status}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// Component for displaying backtest trading table (similar to CLI)
function BacktestTradingTable({ agentData }: { agentData: AgentDataMap }) {
  const backtestResults = getBacktestPeriods(agentData);
  if (backtestResults.length === 0) {
    return null;
  }
  
  // Build table rows similar to CLI format
  const tableRows: ActivityRow[] = [];
  
  backtestResults.forEach((backtestResult) => {
    // Add ticker rows for this period
    if (backtestResult.ticker_details) {
      backtestResult.ticker_details.forEach((ticker) => {
        tableRows.push({
          type: 'ticker',
          date: backtestResult.date,
          ticker: ticker.ticker,
          action: ticker.action,
          quantity: ticker.quantity,
          price: ticker.price,
          shares_owned: ticker.shares_owned,
          long_shares: ticker.long_shares,
          short_shares: ticker.short_shares,
          position_value: ticker.position_value,
          bullish_count: ticker.bullish_count,
          bearish_count: ticker.bearish_count,
          neutral_count: ticker.neutral_count,
        });
      });
    }
    
    // Add portfolio summary row for this period
    tableRows.push({
      type: 'summary',
      date: backtestResult.date,
      portfolio_value: backtestResult.portfolio_value,
      cash: backtestResult.cash,
      portfolio_return: backtestResult.portfolio_return,
      total_position_value: backtestResult.portfolio_value - backtestResult.cash,
      performance_metrics: backtestResult.performance_metrics,
    });
  });
    
  // Sort by date descending (newest first) and show only the last 50 rows to avoid performance issues
  const recentRows = tableRows
    .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())
    .slice(0, 50);
  
  
  return (
    <Card className="bg-transparent mb-4">
      <CardHeader>
        <CardTitle className="text-lg">Activity</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="max-h-96 overflow-y-auto">
          <Table>
            {/* R20-S7 GAMMA A-3: WCAG 2.1 caption — sr-only so it's invisible to sighted users
                but read by screen readers to announce the table's purpose. */}
            <TableCaption className="sr-only">回测交易活动表（按日期 / 标的列出每笔买入卖出）</TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead>Ticker</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Quantity</TableHead>
                <TableHead>Price</TableHead>
                <TableHead>Shares</TableHead>
                <TableHead>Position Value</TableHead>
                <TableHead>Bullish</TableHead>
                <TableHead>Bearish</TableHead>
                <TableHead>Neutral</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recentRows.map((row, idx: number) => {
                if (row.type === 'ticker') {
                  return (
                    // R20-S6 GAMMA A-4: composite key (date+ticker+idx) instead of bare idx so React
                    // can correctly diff rows when the recent-rows window scrolls / reorders.
                    <TableRow key={`${row.date}-${row.ticker}-${idx}`}>
                      <TableCell className="font-medium">{row.date}</TableCell>
                      <TableCell className="font-medium text-cyan-500">{row.ticker}</TableCell>
                      <TableCell>
                        <span className={cn("font-medium", getActionColor(row.action || ''))}>
                          {row.action?.toUpperCase() || 'HOLD'}
                        </span>
                      </TableCell>
                      <TableCell className={cn("font-medium", getActionColor(row.action || ''))}>
                        {row.quantity?.toLocaleString() || 0}
                      </TableCell>
                      <TableCell>${row.price?.toFixed(2) || '0.00'}</TableCell>
                      <TableCell>{row.shares_owned?.toLocaleString() || 0}</TableCell>
                      <TableCell className="text-primary">
                        ${row.position_value?.toLocaleString() || '0'}
                      </TableCell>
                      <TableCell className="text-green-500">{row.bullish_count || 0}</TableCell>
                      <TableCell className="text-red-500">{row.bearish_count || 0}</TableCell>
                      <TableCell className="text-blue-500">{row.neutral_count || 0}</TableCell>
                    </TableRow>
                  );
                }
              })}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}

// Component for displaying backtest results
function BacktestResults({ outputData }: { outputData: OutputNodeData | null }) {
  if (!outputData) {
    return null;
  }
  
  if (!outputData.performance_metrics) {
    return (
      <Card className="bg-transparent mb-4">
        <CardHeader>
          <CardTitle className="text-lg">Backtest Results</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-8 text-muted-foreground">
            Backtest completed. Performance metrics will appear here.
          </div>
        </CardContent>
      </Card>
    );
  }
  
  const { performance_metrics, final_portfolio, total_days } = outputData;
  
  return (
    <Card className="bg-transparent mb-4">
      <CardHeader>
        <CardTitle className="text-lg">Backtest Results</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
          {/* Performance Metrics */}
          <div className="space-y-2">
            <h4 className="font-medium">Performance Metrics</h4>
            <div className="space-y-1 text-sm">
              {performance_metrics.sharpe_ratio !== null && performance_metrics.sharpe_ratio !== undefined && (
                <div className="flex justify-between">
                  <span>Sharpe Ratio:</span>
                  <span className={cn("font-medium", performance_metrics.sharpe_ratio > 1 ? "text-green-500" : "text-red-500")}>
                    {performance_metrics.sharpe_ratio.toFixed(2)}
                  </span>
                </div>
              )}
              {performance_metrics.sortino_ratio !== null && performance_metrics.sortino_ratio !== undefined && (
                <div className="flex justify-between">
                  <span>Sortino Ratio:</span>
                  <span className={cn("font-medium", performance_metrics.sortino_ratio > 1 ? "text-green-500" : "text-red-500")}>
                    {performance_metrics.sortino_ratio.toFixed(2)}
                  </span>
                </div>
              )}
              {performance_metrics.max_drawdown !== null && performance_metrics.max_drawdown !== undefined && (
                <div className="flex justify-between">
                  <span>Max Drawdown:</span>
                  <span className="font-medium text-red-500">
                    {Math.abs(performance_metrics.max_drawdown).toFixed(2)}%
                  </span>
                </div>
              )}
            </div>
          </div>
          
          {/* Portfolio Summary */}
          <div className="space-y-2">
            <h4 className="font-medium">Portfolio Summary</h4>
            <div className="space-y-1 text-sm">
              <div className="flex justify-between">
                <span>Total Days:</span>
                <span className="font-medium">{total_days}</span>
              </div>
              <div className="flex justify-between">
                <span>Final Cash:</span>
                <span className="font-medium">${(final_portfolio?.cash ?? 0).toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span>Margin Used:</span>
                <span className="font-medium">${(final_portfolio?.margin_used ?? 0).toLocaleString()}</span>
              </div>
            </div>
          </div>
          
          {/* Exposure Metrics */}
          <div className="space-y-2">
            <h4 className="font-medium">Exposure Metrics</h4>
            <div className="space-y-1 text-sm">
              {performance_metrics.gross_exposure !== null && performance_metrics.gross_exposure !== undefined && (
                <div className="flex justify-between">
                  <span>Gross Exposure:</span>
                  <span className="font-medium">${performance_metrics.gross_exposure.toLocaleString()}</span>
                </div>
              )}
              {performance_metrics.net_exposure !== null && performance_metrics.net_exposure !== undefined && (
                <div className="flex justify-between">
                  <span>Net Exposure:</span>
                  <span className="font-medium">${performance_metrics.net_exposure.toLocaleString()}</span>
                </div>
              )}
              {performance_metrics.long_short_ratio !== null && performance_metrics.long_short_ratio !== undefined && (
                <div className="flex justify-between">
                  <span>Long/Short Ratio:</span>
                  <span className="font-medium">
                    {performance_metrics.long_short_ratio === Infinity || performance_metrics.long_short_ratio === null ? '∞' : performance_metrics.long_short_ratio.toFixed(2)}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
        
        {/* Final Positions */}
        {final_portfolio?.positions && (
          <div>
            <h4 className="font-medium mb-2">Final Positions</h4>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ticker</TableHead>
                  <TableHead>Long Shares</TableHead>
                  <TableHead>Short Shares</TableHead>
                  <TableHead>Long Cost Basis</TableHead>
                  <TableHead>Short Cost Basis</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(final_portfolio.positions).map(([ticker, position]: [string, PortfolioPositionData]) => {
                  const longShares = typeof position.long === 'number' ? position.long : 0;
                  const shortShares = typeof position.short === 'number' ? position.short : 0;
                  const longCostBasis = typeof position.long_cost_basis === 'number' ? position.long_cost_basis : 0;
                  const shortCostBasis = typeof position.short_cost_basis === 'number' ? position.short_cost_basis : 0;
                  return (
                    <TableRow key={ticker}>
                      <TableCell className="font-medium">{ticker}</TableCell>
                      <TableCell className={cn(longShares > 0 ? "text-green-500" : "text-muted-foreground")}>
                        {longShares}
                      </TableCell>
                      <TableCell className={cn(shortShares > 0 ? "text-red-500" : "text-muted-foreground")}>
                        {shortShares}
                      </TableCell>
                      <TableCell>${longCostBasis.toFixed(2)}</TableCell>
                      <TableCell>${shortCostBasis.toFixed(2)}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Component for displaying real-time backtest performance
function BacktestPerformanceMetrics({ agentData }: { agentData: AgentDataMap }) {
  const backtestResults = getBacktestPeriods(agentData);
  if (backtestResults.length === 0) return null;
  
  const firstPeriod = backtestResults[0];
  const latestPeriod = backtestResults[backtestResults.length - 1];
  
  // Calculate performance metrics
  const initialValue = firstPeriod.portfolio_value;
  const currentValue = latestPeriod.portfolio_value;
  const totalReturn = ((currentValue - initialValue) / initialValue) * 100;
  
  // Calculate win rate (periods with positive returns)
  const periodReturns = backtestResults.slice(1).map((period, idx: number) => {
    const prevPeriod = backtestResults[idx];
    return ((period.portfolio_value - prevPeriod.portfolio_value) / prevPeriod.portfolio_value) * 100;
  });
  
  const winningPeriods = periodReturns.filter((ret: number) => ret > 0).length;
  const winRate = periodReturns.length > 0 ? (winningPeriods / periodReturns.length) * 100 : 0;
  
  // Calculate max drawdown
  let maxDrawdown = 0;
  let peak = initialValue;
  
  backtestResults.forEach((period) => {
    if (period.portfolio_value > peak) {
      peak = period.portfolio_value;
    }
    const drawdown = ((period.portfolio_value - peak) / peak) * 100;
    if (drawdown < maxDrawdown) {
      maxDrawdown = drawdown;
    }
  });
  
  return (
    <Card className="bg-transparent mb-4">
      <CardHeader>
        <CardTitle className="text-lg">Performance</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="text-center">
            <div className="text-xs text-muted-foreground">Total Return</div>
            <div className={cn("font-sm", totalReturn >= 0 ? "text-green-500" : "text-red-500")}>
              {totalReturn >= 0 ? '+' : ''}{totalReturn.toFixed(2)}%
            </div>
          </div>
          <div className="text-center">
            <div className="text-xs text-muted-foreground">Win Rate</div>
            <div className="font-sm">{winRate.toFixed(1)}%</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-muted-foreground">Max Drawdown</div>
            <div className="font-sm text-red-500">{Math.abs(maxDrawdown).toFixed(2)}%</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-muted-foreground">Periods Traded</div>
            <div className="font-sm">{backtestResults.length}</div>
          </div>
        </div>
        
        {/* Additional metrics */}
        <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="text-center">
            <div className="text-xs text-muted-foreground">Current Value</div>
            <div className="font-sm">${currentValue?.toLocaleString()}</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-muted-foreground">Initial Value</div>
            <div className="font-sm">${initialValue?.toLocaleString()}</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-muted-foreground">P&L</div>
            <div className={cn("font-sm", totalReturn >= 0 ? "text-green-500" : "text-red-500")}>
              ${(currentValue - initialValue).toLocaleString()}
            </div>
          </div>
          <div className="text-center">
            <div className="text-xs text-muted-foreground">Long/Short Ratio</div>
            <div className="font-sm">
              {latestPeriod.long_short_ratio === Infinity || latestPeriod.long_short_ratio === null ? '∞' : latestPeriod.long_short_ratio?.toFixed(2)}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// R20.10 GAMMA: 5-state machine for backtest rendering.
// Detects IDLE / LOADING / STREAMING / COMPLETE / ERROR based on agentData
// and outputData, so the user always sees meaningful content instead of
// blank space during a backtest run.
function detectBacktestState(agentData: AgentDataMap, outputData: OutputNodeData | null): 'idle' | 'loading' | 'streaming' | 'complete' {
  const backtestAgent = agentData?.['backtest'];
  if (outputData?.performance_metrics) {
    return 'complete';
  }
  if (!backtestAgent) {
    return 'idle';
  }
  const hasResults = backtestAgent.backtestResults && backtestAgent.backtestResults.length > 0;
  return hasResults ? 'streaming' : 'loading';
}

// R20.10 GAMMA: Skeleton placeholder for LOADING/STREAMING states.
function BacktestSkeleton({ state }: { state: 'loading' | 'streaming' }) {
  return (
    <Card className="bg-transparent mb-4">
      <CardHeader className="pb-2">
        <CardTitle className="text-lg flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full bg-cyan-500 animate-pulse" />
          {state === 'loading' ? '回测启动中…' : '回测进行中…'}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-16 rounded-lg bg-muted/40 animate-pulse" />
          ))}
        </div>
        <div className="h-48 rounded-lg bg-muted/30 animate-pulse mb-2" />
        <div className="h-24 rounded-lg bg-muted/20 animate-pulse" />
        <p className="text-xs text-muted-foreground mt-3">
          {state === 'loading'
            ? '正在获取历史价格数据并初始化策略…'
            : '正在逐日模拟交易，部分结果已开始流式返回…'}
        </p>
      </CardContent>
    </Card>
  );
}

// Main component for backtest output
export function BacktestOutput({
  agentData,
  outputData
}: {
  agentData: AgentDataMap;
  outputData: OutputNodeData | null;
}) {
  return (
    <ErrorBoundary>
      <BacktestOutputInner agentData={agentData} outputData={outputData} />
    </ErrorBoundary>
  );
}

// R20.15 GAMMA: Inner component wrapped by ErrorBoundary to prevent the
// whole BacktestOutput region from going white-screen when malformed
// streaming data (NaN, missing fields) triggers a render-time exception.
function BacktestOutputInner({
  agentData,
  outputData
}: {
  agentData: AgentDataMap;
  outputData: OutputNodeData | null;
}) {
  const state = detectBacktestState(agentData, outputData);

  // IDLE: no backtest has been started yet — render nothing (caller decides
  // whether to show an empty-state hint).
  if (state === 'idle') {
    return null;
  }

  // LOADING / STREAMING: show skeleton + progress so the user sees activity.
  if (state === 'loading' || state === 'streaming') {
    return (
      <>
        <BacktestProgress agentData={agentData} />
        <BacktestSkeleton state={state} />
        {state === 'streaming' && <BacktestEquityCurve agentData={agentData} />}
        {state === 'streaming' && <BacktestTradingTable agentData={agentData} />}
      </>
    );
  }

  // COMPLETE: render full results.
  return (
    <>
      <BacktestProgress agentData={agentData} />
      {/* P0-4: Equity Curve Visualization — renders above results */}
      <BacktestEquityCurve agentData={agentData} />
      {outputData && <BacktestResults outputData={outputData} />}
      {agentData && agentData['backtest'] && (
        <BacktestPerformanceMetrics agentData={agentData} />
      )}
      <BacktestTradingTable agentData={agentData} />

    </>
  );
} 