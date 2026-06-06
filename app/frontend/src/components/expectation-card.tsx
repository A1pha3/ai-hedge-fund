import { AlertTriangle, BarChart3 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

/**
 * P0 OPT-C: empirical per-ticker expectation rendered in
 * InvestmentReportDialog. Mirrors the data shape produced by the backend
 * `src.portfolio.stock_history_expectation.compute_stock_history_expectation`
 * helper. When the backend API is not yet wired, the card accepts `null` /
 * `undefined` for the per-field metrics and renders a small-sample banner.
 */
export interface StockHistoryExpectationData {
  ticker: string;
  n_trades: number;
  win_rate: number | null;
  avg_30d_return: number | null;
  worst_30d_return: number | null;
  best_30d_return: number | null;
  is_small_sample: boolean;
  lookback_days: number;
  period_start: string;
  period_end: string;
}

interface ExpectationCardProps {
  data: StockHistoryExpectationData;
}

function formatPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}%`;
}

function winRateColor(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return 'text-muted-foreground';
  if (rate >= 0.6) return 'text-green-500';
  if (rate >= 0.45) return 'text-green-400';
  if (rate >= 0.35) return 'text-red-400';
  return 'text-red-500';
}

function avgColor(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'text-muted-foreground';
  if (value > 0) return 'text-green-500';
  return 'text-red-500';
}

export function ExpectationCard({ data }: ExpectationCardProps) {
  const {
    ticker,
    n_trades,
    win_rate,
    avg_30d_return,
    worst_30d_return,
    best_30d_return,
    is_small_sample,
    lookback_days,
    period_start,
    period_end,
  } = data;

  return (
    <Card
      data-testid="expectation-card"
      data-ticker={ticker}
      data-small-sample={is_small_sample ? 'true' : 'false'}
    >
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-base font-semibold">
            {ticker} 30-Day Expectation
          </CardTitle>
          <BarChart3 className="h-4 w-4 text-muted-foreground" />
        </div>
        <CardDescription>
          {n_trades > 0
            ? `${n_trades} 笔成交 · ${lookback_days} 日窗口 (${period_start} → ${period_end})`
            : `${lookback_days} 日窗口 (${period_start} → ${period_end})`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {is_small_sample ? (
          <div
            data-testid="small-sample-warning"
            className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-50/40 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
          >
            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
            <div>
              <p className="font-medium">小样本警告</p>
              <p className="opacity-80">
                成交数 &lt; 5, 统计不可靠。建议结合其他信号使用。
              </p>
            </div>
          </div>
        ) : null}

        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <p className="text-xs text-muted-foreground">Win Rate</p>
            <p
              data-testid="expectation-win-rate"
              className={`text-lg font-semibold ${winRateColor(win_rate)}`}
            >
              {win_rate === null || win_rate === undefined
                ? '--'
                : `${(win_rate * 100).toFixed(1)}%`}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Avg 30D Return</p>
            <p
              data-testid="expectation-avg-return"
              className={`text-lg font-semibold ${avgColor(avg_30d_return)}`}
            >
              {formatPct(avg_30d_return)}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Worst 30D</p>
            <p
              data-testid="expectation-worst"
              className={`text-base font-medium ${avgColor(worst_30d_return)}`}
            >
              {formatPct(worst_30d_return)}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Best 30D</p>
            <p
              data-testid="expectation-best"
              className={`text-base font-medium ${avgColor(best_30d_return)}`}
            >
              {formatPct(best_30d_return)}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 pt-1">
          <Badge
            variant={n_trades >= 5 ? 'success' : 'warning'}
            data-testid="expectation-sample-badge"
          >
            {n_trades >= 5 ? `n=${n_trades} 可靠` : `n=${n_trades} 小样本`}
          </Badge>
        </div>
      </CardContent>
    </Card>
  );
}
