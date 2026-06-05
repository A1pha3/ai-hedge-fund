import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { TrendingUp, TrendingDown, ShieldAlert, Activity } from 'lucide-react';

export interface EdgeCardData {
  /** Expected 30-day edge (percentage return). Positive = bullish, negative = bearish. */
  expected_30d_edge: number | null | undefined;
  /** CVaR(95%) single-stock exposure as a fraction (e.g. 0.08 = 8% tail risk). */
  cvar_95: number | null | undefined;
  /** Current risk budget ratio (0..1 where 1 = budget fully consumed). */
  risk_budget_ratio: number | null | undefined;
  /** Machine-generated one-line explanation of the edge. */
  edge_summary: string | null | undefined;
}

interface EdgeCardProps {
  ticker: string;
  data: EdgeCardData;
}

function formatPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}%`;
}

function formatRatio(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '--';
  return `${(value * 100).toFixed(digits)}%`;
}

function edgeColor(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'text-muted-foreground';
  if (value > 2) return 'text-green-500';
  if (value > 0) return 'text-green-400';
  if (value > -2) return 'text-red-400';
  return 'text-red-500';
}

function riskBudgetVariant(
  ratio: number | null | undefined,
): 'outline' | 'warning' | 'destructive' | 'success' {
  if (ratio === null || ratio === undefined) return 'outline';
  if (ratio >= 0.9) return 'destructive';
  if (ratio >= 0.7) return 'warning';
  return 'success';
}

function edgeIcon(value: number | null | undefined) {
  if (value === null || value === undefined) return <Activity className="h-4 w-4 text-muted-foreground" />;
  if (value > 0) return <TrendingUp className="h-4 w-4 text-green-500" />;
  return <TrendingDown className="h-4 w-4 text-red-500" />;
}

export function EdgeCard({ ticker, data }: EdgeCardProps) {
  const hasAnyData =
    data.expected_30d_edge !== null && data.expected_30d_edge !== undefined;

  return (
    <Card className="overflow-hidden">
      <CardHeader className="bg-muted/50 pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            {edgeIcon(data.expected_30d_edge)}
            30D Edge — {ticker}
          </CardTitle>
          {hasAnyData ? (
            <Badge variant={data.expected_30d_edge! > 0 ? 'success' : 'destructive'}>
              {formatPct(data.expected_30d_edge)}
            </Badge>
          ) : (
            <Badge variant="outline">N/A</Badge>
          )}
        </div>
        {!hasAnyData && (
          <CardDescription>
            Edge data not yet available for this ticker.
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="pt-3">
        <div className="grid grid-cols-3 gap-4">
          {/* Expected 30D Edge */}
          <div className="space-y-1">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Expected 30D Edge
            </p>
            <p className={`text-lg font-bold ${edgeColor(data.expected_30d_edge)}`}>
              {formatPct(data.expected_30d_edge)}
            </p>
          </div>

          {/* CVaR(95%) */}
          <div className="space-y-1">
            <p className="text-xs uppercase tracking-wide text-muted-foreground flex items-center gap-1">
              <ShieldAlert className="h-3 w-3" />
              CVaR(95%)
            </p>
            <p className="text-lg font-bold text-foreground">
              {data.cvar_95 !== null && data.cvar_95 !== undefined
                ? formatPct(data.cvar_95)
                : '--'}
            </p>
          </div>

          {/* Risk Budget Ratio */}
          <div className="space-y-1">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Risk Budget Used
            </p>
            <div className="flex items-center gap-2">
              <p className="text-lg font-bold text-foreground">
                {formatRatio(data.risk_budget_ratio)}
              </p>
              <Badge variant={riskBudgetVariant(data.risk_budget_ratio)}>
                {data.risk_budget_ratio !== null && data.risk_budget_ratio !== undefined
                  ? data.risk_budget_ratio >= 0.9
                    ? 'Full'
                    : data.risk_budget_ratio >= 0.7
                      ? 'High'
                      : 'OK'
                  : '--'}
              </Badge>
            </div>
          </div>
        </div>

        {/* One-line summary */}
        {data.edge_summary && (
          <p className="mt-3 text-sm text-muted-foreground border-t border-border/60 pt-3">
            {data.edge_summary}
          </p>
        )}

        {/* Risk budget progress bar */}
        {data.risk_budget_ratio !== null && data.risk_budget_ratio !== undefined && (
          <div className="mt-3 border-t border-border/60 pt-3">
            <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
              <span>Risk Budget</span>
              <span>{(data.risk_budget_ratio * 100).toFixed(0)}%</span>
            </div>
            <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  data.risk_budget_ratio >= 0.9
                    ? 'bg-red-500'
                    : data.risk_budget_ratio >= 0.7
                      ? 'bg-yellow-500'
                      : 'bg-green-500'
                }`}
                style={{ width: `${Math.min(100, data.risk_budget_ratio * 100)}%` }}
              />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
