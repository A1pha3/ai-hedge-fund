/**
 * P2 2.3: Portfolio Adjustment Simulator — "cancel / reduce" one-click simulator.
 *
 * A dialog component that:
 * 1. Lists all planned trading decisions (from the output node)
 * 2. Lets users "cancel" a planned operation or "reduce" a position by a percentage
 * 3. Shows before/after risk metrics (HHI, CVaR, total NAV, position count)
 *    with green/red delta indicators for improvement / deterioration
 *
 * This is a pure simulation — no actual trades are executed.
 */
import { useState, useCallback } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { FlaskConical, X, Minus, ArrowUp, ArrowDown, MinusIcon } from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Decision {
  action: string;
  quantity: number;
  confidence?: number;
  reasoning?: string;
}

interface Position {
  long: number;
  short: number;
  long_cost_basis?: number;
  short_cost_basis?: number;
}

type AdjustmentOperation = 'none' | 'cancel' | 'reduce';

interface AdjustmentState {
  operation: AdjustmentOperation;
  reducePct: number; // 0..1
}

interface SimResponse {
  before: RiskSnapshot;
  after: RiskSnapshot;
  delta: RiskDelta;
  ticker_results: TickerResult[];
}

interface RiskSnapshot {
  hhi: number;
  short_ratio: number;
  cvar_95: number;
  position_count: number;
  max_single_position_weight: number;
  total_nav: number;
  total_long: number;
  total_short: number;
}

interface RiskDelta {
  hhi: number;
  short_ratio: number;
  cvar_95: number;
  position_count: number;
  max_single_position_weight: number;
  total_nav: number;
  total_long: number;
  total_short: number;
}

interface TickerResult {
  ticker: string;
  original_action: string;
  simulated_action: string;
  original_quantity: number;
  simulated_quantity: number;
  operation_applied: string | null;
  reduce_pct: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function fmtPct(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

function fmtUSD(value: number): string {
  if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(2)}M`;
  if (Math.abs(value) >= 1e3) return `$${(value / 1e3).toFixed(1)}K`;
  return `$${value.toFixed(0)}`;
}

function actionBadgeVariant(action: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (action) {
    case 'buy': return 'default';
    case 'sell': return 'destructive';
    case 'short': return 'destructive';
    case 'cover': return 'secondary';
    default: return 'outline';
  }
}

function deltaColor(value: number): string {
  if (value > 0.0005) return 'text-red-500';
  if (value < -0.0005) return 'text-green-500';
  return 'text-muted-foreground';
}

function deltaIcon(value: number) {
  if (value > 0.0005) return <ArrowUp className="h-3 w-3 inline" />;
  if (value < -0.0005) return <ArrowDown className="h-3 w-3 inline" />;
  return <MinusIcon className="h-3 w-3 inline" />;
}

function fmtDelta(value: number): string {
  const sign = value >= 0 ? '+' : '';
  if (Math.abs(value) >= 1) return `${sign}${value.toFixed(0)}`;
  return `${sign}${(value * 100).toFixed(1)}%`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface AdjustmentSimulatorProps {
  decisions: Record<string, Decision>;
  positions?: Record<string, Position>;
  currentPrices?: Record<string, number>;
  cash?: number;
}

export function AdjustmentSimulator({
  decisions,
  positions = {},
  currentPrices = {},
  cash = 0,
}: AdjustmentSimulatorProps) {
  const [adjustments, setAdjustments] = useState<Record<string, AdjustmentState>>({});
  const [simResult, setSimResult] = useState<SimResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tickers = Object.keys(decisions).length > 0
    ? Object.keys(decisions)
    : Object.keys(positions);

  const setAdjustment = useCallback((ticker: string, op: AdjustmentOperation, pct?: number) => {
    setAdjustments(prev => ({
      ...prev,
      [ticker]: { operation: op, reducePct: pct ?? prev[ticker]?.reducePct ?? 0.5 },
    }));
  }, []);

  const clearAdjustment = useCallback((ticker: string) => {
    setAdjustments(prev => {
      const next = { ...prev };
      delete next[ticker];
      return next;
    });
  }, []);

  const runSimulation = useCallback(async () => {
    setLoading(true);
    setError(null);

    const adjustmentList = Object.entries(adjustments)
      .filter(([, adj]) => adj.operation !== 'none')
      .map(([ticker, adj]) => ({
        ticker,
        operation: adj.operation,
        reduce_pct: adj.reducePct,
      }));

    try {
      const resp = await fetch(`${API_BASE_URL}/portfolio/simulate-adjustment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          positions,
          current_prices: currentPrices,
          decisions,
          cash,
          adjustments: adjustmentList,
        }),
      });

      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP ${resp.status}`);
      }

      const data: SimResponse = await resp.json();
      setSimResult(data);
    } catch (err: any) {
      setError(err.message || 'Simulation failed');
    } finally {
      setLoading(false);
    }
  }, [adjustments, positions, currentPrices, decisions, cash]);

  const hasAdjustments = Object.values(adjustments).some(a => a.operation !== 'none');

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" data-testid="simulator-trigger">
          <FlaskConical className="h-4 w-4 mr-2" />
          Simulate Adjustments
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto" data-testid="simulator-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FlaskConical className="h-5 w-5" />
            Adjustment Simulator
          </DialogTitle>
          <DialogDescription>
            Simulate canceling or reducing planned operations. No actual trades are executed.
          </DialogDescription>
        </DialogHeader>

        {/* Decision Table */}
        <div className="space-y-4">
          <Table data-testid="simulator-table">
            <TableHeader>
              <TableRow>
                <TableHead>Ticker</TableHead>
                <TableHead>Planned</TableHead>
                <TableHead className="text-center">Cancel</TableHead>
                <TableHead className="text-center">Reduce</TableHead>
                <TableHead className="text-right">Reduce %</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tickers.map(ticker => {
                const decision = decisions[ticker] || { action: 'hold', quantity: 0 };
                const adj = adjustments[ticker] || { operation: 'none', reducePct: 0.5 };

                return (
                  <TableRow key={ticker} data-testid={`simulator-row-${ticker}`}>
                    <TableCell className="font-mono font-medium">{ticker}</TableCell>
                    <TableCell>
                      <Badge variant={actionBadgeVariant(decision.action)}>
                        {decision.action.toUpperCase()}
                        {decision.quantity > 0 && ` x${decision.quantity}`}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-center">
                      <Button
                        variant={adj.operation === 'cancel' ? 'destructive' : 'outline'}
                        size="sm"
                        onClick={() => {
                          if (adj.operation === 'cancel') {
                            clearAdjustment(ticker);
                          } else {
                            setAdjustment(ticker, 'cancel');
                          }
                        }}
                        data-testid={`cancel-btn-${ticker}`}
                      >
                        <X className="h-3 w-3" />
                      </Button>
                    </TableCell>
                    <TableCell className="text-center">
                      <Button
                        variant={adj.operation === 'reduce' ? 'secondary' : 'outline'}
                        size="sm"
                        onClick={() => {
                          if (adj.operation === 'reduce') {
                            clearAdjustment(ticker);
                          } else {
                            setAdjustment(ticker, 'reduce', 0.5);
                          }
                        }}
                        data-testid={`reduce-btn-${ticker}`}
                      >
                        <Minus className="h-3 w-3" />
                      </Button>
                    </TableCell>
                    <TableCell className="text-right">
                      {adj.operation === 'reduce' ? (
                        <Input
                          type="number"
                          min={1}
                          max={100}
                          value={Math.round(adj.reducePct * 100)}
                          onChange={e => {
                            const val = Math.min(100, Math.max(1, parseInt(e.target.value) || 1));
                            setAdjustment(ticker, 'reduce', val / 100);
                          }}
                          className="w-16 text-right text-sm"
                          data-testid={`reduce-pct-${ticker}`}
                        />
                      ) : (
                        <span className="text-muted-foreground text-sm">--</span>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>

          {/* Run Simulation Button */}
          <div className="flex items-center gap-3">
            <Button
              onClick={runSimulation}
              disabled={loading || !hasAdjustments}
              data-testid="run-simulation-btn"
            >
              {loading ? 'Simulating...' : 'Run Simulation'}
            </Button>
            {error && (
              <span className="text-red-500 text-sm" data-testid="sim-error">{error}</span>
            )}
          </div>

          {/* Results */}
          {simResult && (
            <div className="space-y-4 mt-4" data-testid="sim-results">
              {/* Risk Metrics Comparison */}
              <div className="rounded-md border border-border/60 p-4 space-y-3">
                <h4 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  Risk Metrics Comparison
                </h4>

                {/* Metrics Grid */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4" data-testid="metrics-grid">
                  <MetricCard
                    label="HHI"
                    before={simResult.before.hhi}
                    after={simResult.after.hhi}
                    delta={simResult.delta.hhi}
                    format="decimal"
                  />
                  <MetricCard
                    label="CVaR (95%)"
                    before={simResult.before.cvar_95}
                    after={simResult.after.cvar_95}
                    delta={simResult.delta.cvar_95}
                    format="pct"
                  />
                  <MetricCard
                    label="Total NAV"
                    before={simResult.before.total_nav}
                    after={simResult.after.total_nav}
                    delta={simResult.delta.total_nav}
                    format="usd"
                    invertDelta
                  />
                  <MetricCard
                    label="Positions"
                    before={simResult.before.position_count}
                    after={simResult.after.position_count}
                    delta={simResult.delta.position_count}
                    format="int"
                  />
                  <MetricCard
                    label="Short Ratio"
                    before={simResult.before.short_ratio}
                    after={simResult.after.short_ratio}
                    delta={simResult.delta.short_ratio}
                    format="pct"
                  />
                  <MetricCard
                    label="Max Position Wt"
                    before={simResult.before.max_single_position_weight}
                    after={simResult.after.max_single_position_weight}
                    delta={simResult.delta.max_single_position_weight}
                    format="pct"
                  />
                  <MetricCard
                    label="Total Long"
                    before={simResult.before.total_long}
                    after={simResult.after.total_long}
                    delta={simResult.delta.total_long}
                    format="usd"
                  />
                  <MetricCard
                    label="Total Short"
                    before={simResult.before.total_short}
                    after={simResult.after.total_short}
                    delta={simResult.delta.total_short}
                    format="usd"
                  />
                </div>
              </div>

              {/* Per-Ticker Results */}
              {simResult.ticker_results.length > 0 && (
                <div className="rounded-md border border-border/60 p-4">
                  <h4 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground mb-3">
                    Per-Ticker Results
                  </h4>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Ticker</TableHead>
                        <TableHead>Original</TableHead>
                        <TableHead>Simulated</TableHead>
                        <TableHead>Operation</TableHead>
                        <TableHead className="text-right">Reduce %</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {simResult.ticker_results.map((r) => (
                        <TableRow key={r.ticker} data-testid={`result-row-${r.ticker}`}>
                          <TableCell className="font-mono">{r.ticker}</TableCell>
                          <TableCell>
                            <Badge variant={actionBadgeVariant(r.original_action)}>
                              {r.original_action.toUpperCase()}
                              {r.original_quantity > 0 && ` x${r.original_quantity}`}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <Badge variant={actionBadgeVariant(r.simulated_action)}>
                              {r.simulated_action.toUpperCase()}
                              {r.simulated_quantity > 0 && ` x${r.simulated_quantity}`}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            {r.operation_applied ? (
                              <Badge variant={r.operation_applied === 'cancel' ? 'destructive' : 'secondary'}>
                                {r.operation_applied}
                              </Badge>
                            ) : (
                              <span className="text-muted-foreground text-xs">none</span>
                            )}
                          </TableCell>
                          <TableCell className="text-right">
                            {r.reduce_pct > 0 ? `${Math.round(r.reduce_pct * 100)}%` : '--'}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// MetricCard sub-component
// ---------------------------------------------------------------------------

interface MetricCardProps {
  label: string;
  before: number;
  after: number;
  delta: number;
  format: 'decimal' | 'pct' | 'usd' | 'int';
  /** If true, positive delta = good (e.g. NAV). Default: negative delta = good (risk metrics). */
  invertDelta?: boolean;
}

function MetricCard({ label, before, after, delta, format, invertDelta = false }: MetricCardProps) {
  const isGood = invertDelta ? delta > 0.0005 : delta < -0.0005;
  const isBad = invertDelta ? delta < -0.0005 : delta > 0.0005;

  function fmtValue(v: number): string {
    switch (format) {
      case 'decimal': return v.toFixed(4);
      case 'pct': return fmtPct(v);
      case 'usd': return fmtUSD(v);
      case 'int': return String(Math.round(v));
    }
  }

  function fmtDeltaValue(d: number): string {
    switch (format) {
      case 'decimal': return `${d >= 0 ? '+' : ''}${d.toFixed(4)}`;
      case 'pct': return `${d >= 0 ? '+' : ''}${fmtPct(d)}`;
      case 'usd': return `${d >= 0 ? '+' : ''}${fmtUSD(d)}`;
      case 'int': return `${d >= 0 ? '+' : ''}${Math.round(d)}`;
    }
  }

  const colorClass = isGood ? 'text-green-500' : isBad ? 'text-red-500' : 'text-muted-foreground';

  return (
    <div className="space-y-1 p-2 rounded-md bg-muted/20" data-testid={`metric-${label.toLowerCase().replace(/\s+/g, '-')}`}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-semibold">{fmtValue(after)}</p>
      <p className={`text-xs ${colorClass}`} data-testid={`metric-delta-${label.toLowerCase().replace(/\s+/g, '-')}`}>
        {deltaIcon(delta)} {fmtDeltaValue(delta)}
      </p>
    </div>
  );
}
