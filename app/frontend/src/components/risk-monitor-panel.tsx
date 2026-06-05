import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import type { RiskMetrics } from '@/contexts/node-context';
import { AlertTriangle, BarChart3, Shield, TrendingDown } from 'lucide-react';

/**
 * P1 1.5: Risk Monitor Panel — portfolio-level risk gauges.
 *
 * Renders:
 * - HHI concentration gauge (color-coded arc + number)
 * - CVaR(95%) card with green/yellow/red threshold
 * - Short ratio badge
 * - Industry exposure horizontal bar chart (div-width bars, no chart lib)
 *
 * All visual elements use shadcn/ui Card + Badge + Tailwind div-width bars.
 */

interface RiskMonitorPanelProps {
  riskMetrics: RiskMetrics | undefined | null;
}

// ---------- Helpers ----------

/** Format a decimal as a percentage string (e.g. 0.1534 -> "15.3%"). */
function fmtPct(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

/** Format a dollar value. */
function fmtUSD(value: number): string {
  if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(2)}M`;
  if (Math.abs(value) >= 1e3) return `$${(value / 1e3).toFixed(1)}K`;
  return `$${value.toFixed(0)}`;
}

/** HHI severity: < 0.15 = diversified, 0.15-0.25 = moderate, > 0.25 = concentrated. */
function hhiSeverity(hhi: number): { label: string; color: string; badge: 'success' | 'warning' | 'destructive' } {
  if (hhi < 0.15) return { label: 'Diversified', color: 'text-green-500', badge: 'success' };
  if (hhi < 0.25) return { label: 'Moderate', color: 'text-yellow-500', badge: 'warning' };
  return { label: 'Concentrated', color: 'text-red-500', badge: 'destructive' };
}

/** CVaR severity: < 0.05 = low, 0.05-0.12 = moderate, > 0.12 = high. */
function cvarSeverity(cvar: number): { color: string; bgColor: string; badge: 'success' | 'warning' | 'destructive' } {
  if (cvar < 0.05) return { color: 'text-green-500', bgColor: 'bg-green-500', badge: 'success' };
  if (cvar < 0.12) return { color: 'text-yellow-500', bgColor: 'bg-yellow-500', badge: 'warning' };
  return { color: 'text-red-500', bgColor: 'bg-red-500', badge: 'destructive' };
}

/** Short ratio severity: < 0.1 = low, 0.1-0.3 = moderate, > 0.3 = high. */
function shortRatioSeverity(ratio: number): { label: string; badge: 'success' | 'warning' | 'destructive' } {
  if (ratio < 0.1) return { label: 'Low', badge: 'success' };
  if (ratio < 0.3) return { label: 'Moderate', badge: 'warning' };
  return { label: 'High', badge: 'destructive' };
}

// ---------- Component ----------

export function RiskMonitorPanel({ riskMetrics }: RiskMonitorPanelProps) {
  if (!riskMetrics) {
    return (
      <Card className="overflow-hidden" data-testid="risk-monitor-panel-empty">
        <CardHeader className="bg-muted/50 pb-3">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Risk Monitor</CardTitle>
          </div>
          <CardDescription>
            Run an analysis to see portfolio risk metrics.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const { hhi, short_ratio, industry_exposures, cvar_95, position_count, max_single_position_weight, total_nav, total_long, total_short } = riskMetrics;

  const hhiInfo = hhiSeverity(hhi);
  const cvarInfo = cvarSeverity(cvar_95);
  const shortInfo = shortRatioSeverity(short_ratio);

  return (
    <Card className="overflow-hidden" data-testid="risk-monitor-panel">
      <CardHeader className="bg-muted/50 pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5" />
            <CardTitle className="text-base">Risk Monitor</CardTitle>
          </div>
          <Badge variant="outline">
            {position_count} position{position_count !== 1 ? 's' : ''}
          </Badge>
        </div>
        <CardDescription>
          HHI / CVaR / Short exposure — portfolio-level risk at a glance.
        </CardDescription>
      </CardHeader>

      <CardContent className="pt-4 space-y-6">
        {/* Row 1: Three metric cards */}
        <div className="grid grid-cols-3 gap-4">
          {/* HHI Gauge */}
          <div className="space-y-2" data-testid="hhi-gauge">
            <p className="text-xs uppercase tracking-wide text-muted-foreground flex items-center gap-1">
              <BarChart3 className="h-3 w-3" />
              HHI Concentration
            </p>
            {/* Semi-circular gauge approximation via a half-ring */}
            <div className="relative flex items-end justify-center h-16" data-testid="hhi-arc">
              <svg viewBox="0 0 100 55" className="w-full max-w-[120px]">
                {/* Background arc */}
                <path
                  d="M 10 50 A 40 40 0 0 1 90 50"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="8"
                  className="text-muted/30"
                />
                {/* Filled arc: proportional to HHI (0..1 mapped to the arc) */}
                <path
                  d="M 10 50 A 40 40 0 0 1 90 50"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="8"
                  strokeDasharray={`${hhi * 126.0} 126.0`}
                  strokeLinecap="round"
                  className={
                    hhi < 0.15
                      ? 'text-green-500'
                      : hhi < 0.25
                        ? 'text-yellow-500'
                        : 'text-red-500'
                  }
                  data-testid="hhi-arc-fill"
                />
              </svg>
              {/* Center number */}
              <div className="absolute bottom-0 text-center">
                <span className={`text-xl font-bold ${hhiInfo.color}`} data-testid="hhi-value">
                  {hhi.toFixed(3)}
                </span>
              </div>
            </div>
            <div className="flex items-center justify-center gap-1">
              <Badge variant={hhiInfo.badge as any} data-testid="hhi-badge">
                {hhiInfo.label}
              </Badge>
            </div>
          </div>

          {/* CVaR Card */}
          <div className="space-y-2" data-testid="cvar-card">
            <p className="text-xs uppercase tracking-wide text-muted-foreground flex items-center gap-1">
              <AlertTriangle className="h-3 w-3" />
              CVaR (95%)
            </p>
            <div className="flex items-center justify-center h-16">
              <span className={`text-2xl font-bold ${cvarInfo.color}`} data-testid="cvar-value">
                {fmtPct(cvar_95)}
              </span>
            </div>
            {/* Mini progress bar */}
            <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full ${cvarInfo.bgColor}`}
                style={{ width: `${Math.min(100, cvar_95 * 100 / 0.25 * 100)}%` }}
                data-testid="cvar-bar"
              />
            </div>
            <div className="flex items-center justify-center gap-1">
              <Badge variant={cvarInfo.badge as any} data-testid="cvar-badge">
                {cvar_95 < 0.05 ? 'Low' : cvar_95 < 0.12 ? 'Moderate' : 'High'} Tail Risk
              </Badge>
            </div>
          </div>

          {/* Short Ratio */}
          <div className="space-y-2" data-testid="short-ratio-card">
            <p className="text-xs uppercase tracking-wide text-muted-foreground flex items-center gap-1">
              <TrendingDown className="h-3 w-3" />
              Short Ratio
            </p>
            <div className="flex items-center justify-center h-16">
              <span className={`text-2xl font-bold ${short_ratio > 0.3 ? 'text-red-500' : short_ratio > 0.1 ? 'text-yellow-500' : 'text-green-500'}`} data-testid="short-ratio-value">
                {fmtPct(short_ratio)}
              </span>
            </div>
            <div className="flex items-center justify-center gap-1">
              <Badge variant={shortInfo.badge as any} data-testid="short-ratio-badge">
                {shortInfo.label}
              </Badge>
            </div>
            {/* Supplementary: Long vs Short breakdown */}
            <div className="text-xs text-muted-foreground text-center">
              Long {fmtUSD(total_long)} / Short {fmtUSD(total_short)}
            </div>
          </div>
        </div>

        {/* Row 2: NAV summary bar */}
        <div
          className="flex items-center justify-between rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-sm"
          data-testid="nav-summary"
        >
          <span className="text-muted-foreground">Total NAV</span>
          <span className="font-semibold" data-testid="nav-value">{fmtUSD(total_nav)}</span>
          <span className="text-muted-foreground ml-4">Max Position</span>
          <span className="font-semibold" data-testid="max-position-weight">{fmtPct(max_single_position_weight)}</span>
        </div>

        {/* Row 3: Industry / Ticker exposure bar chart */}
        {industry_exposures && industry_exposures.length > 0 && (
          <div data-testid="exposure-bars">
            <p className="text-xs uppercase tracking-wide text-muted-foreground mb-3">
              Position Exposure Distribution
            </p>
            <div className="space-y-2">
              {industry_exposures.map((item) => {
                const isShort = item.net_value < 0;
                const barWidth = Math.min(100, Math.abs(item.weight) * 100 / Math.max(max_single_position_weight, 0.01) * 80);
                return (
                  <div
                    key={item.ticker}
                    className="flex items-center gap-2"
                    data-testid={`exposure-bar-${item.ticker}`}
                  >
                    <span className="w-20 text-xs font-mono text-right truncate" title={item.ticker}>
                      {item.ticker}
                    </span>
                    <div className="flex-1 h-5 bg-muted/30 rounded-sm overflow-hidden relative">
                      <div
                        className={`h-full rounded-sm transition-all ${
                          isShort
                            ? 'bg-red-500/70'
                            : 'bg-green-500/70'
                        }`}
                        style={{ width: `${barWidth}%` }}
                        data-testid={`exposure-bar-fill-${item.ticker}`}
                      />
                    </div>
                    <span
                      className={`w-16 text-xs font-semibold text-right ${
                        isShort ? 'text-red-500' : 'text-green-500'
                      }`}
                      data-testid={`exposure-pct-${item.ticker}`}
                    >
                      {fmtPct(item.weight)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
