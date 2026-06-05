import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { ArrowUp, ArrowDown, Minus, BarChart3 } from 'lucide-react';

/**
 * Represents a single strategy factor's contribution to the fused score.
 * Mirrors the `top_factors` entries produced by
 * `src/research/artifacts._extract_top_factors`.
 */
export interface FactorContribution {
  name: string;
  direction: number;
  confidence: number;
  completeness: number;
  weight: number;
  contribution: number;
}

export interface FactorContributionChartProps {
  /** Factors to render. Sorted by contribution descending is expected. */
  factors: FactorContribution[];
  /** Optional heading override. */
  title?: string;
  /** Optional description shown below the heading. */
  description?: string;
}

/** Human-readable labels for the canonical strategy names. */
const FACTOR_LABELS: Record<string, string> = {
  trend: 'Trend',
  mean_reversion: 'Mean Reversion',
  fundamental: 'Fundamental',
  event_sentiment: 'Event Sentiment',
};

function factorLabel(name: string): string {
  return FACTOR_LABELS[name] || name.replace(/_/g, ' ');
}

function directionIcon(direction: number) {
  if (direction > 0) return <ArrowUp className="h-3.5 w-3.5 text-green-500" />;
  if (direction < 0) return <ArrowDown className="h-3.5 w-3.5 text-red-500" />;
  return <Minus className="h-3.5 w-3.5 text-muted-foreground" />;
}

function directionBadge(direction: number) {
  if (direction > 0) return <Badge variant="success">Long</Badge>;
  if (direction < 0) return <Badge variant="destructive">Short</Badge>;
  return <Badge variant="outline">Neutral</Badge>;
}

function barColor(direction: number, contribution: number, maxContribution: number): string {
  if (contribution <= 0) return 'bg-muted';
  const ratio = contribution / maxContribution;
  if (direction > 0) {
    return ratio > 0.6 ? 'bg-green-500' : ratio > 0.3 ? 'bg-green-400' : 'bg-green-300';
  }
  if (direction < 0) {
    return ratio > 0.6 ? 'bg-red-500' : ratio > 0.3 ? 'bg-red-400' : 'bg-red-300';
  }
  return 'bg-gray-400';
}

export function FactorContributionChart({
  factors,
  title = 'Layer B/C Factor Contributions',
  description = 'Each factor\'s weight, direction, and contribution to the fused score.',
}: FactorContributionChartProps) {
  if (!factors || factors.length === 0) {
    return null;
  }

  const maxContribution = Math.max(...factors.map((f) => f.contribution), 0.001);
  const totalContribution = factors.reduce((sum, f) => sum + f.contribution, 0);

  return (
    <Card className="overflow-hidden">
      <CardHeader className="bg-muted/50 pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-muted-foreground" />
            {title}
          </CardTitle>
          <Badge variant="outline">
            {factors.length} factor{factors.length !== 1 ? 's' : ''}
          </Badge>
        </div>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="pt-3">
        <div className="space-y-3">
          {factors.map((factor) => {
            const barWidth = maxContribution > 0
              ? (factor.contribution / maxContribution) * 100
              : 0;
            const contributionShare = totalContribution > 0
              ? ((factor.contribution / totalContribution) * 100).toFixed(1)
              : '0.0';

            return (
              <div key={factor.name} className="space-y-1">
                {/* Header row: name + badges */}
                <div
                  className="flex items-center justify-between"
                  data-testid={`factor-row-${factor.name}`}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    {directionIcon(factor.direction)}
                    <span className="text-sm font-medium truncate">
                      {factorLabel(factor.name)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {directionBadge(factor.direction)}
                    <span
                      className="text-xs tabular-nums text-muted-foreground"
                      data-testid={`factor-weight-${factor.name}`}
                    >
                      w={(factor.weight * 100).toFixed(1)}%
                    </span>
                    <span
                      className="text-xs tabular-nums font-semibold text-foreground"
                      data-testid={`factor-share-${factor.name}`}
                    >
                      {contributionShare}%
                    </span>
                  </div>
                </div>

                {/* Horizontal bar */}
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-2.5 rounded-full bg-muted overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${barColor(factor.direction, factor.contribution, maxContribution)}`}
                      style={{ width: `${Math.max(barWidth, 0)}%` }}
                      data-testid={`factor-bar-${factor.name}`}
                    />
                  </div>
                </div>

                {/* Detail row: confidence + completeness */}
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span>
                    conf {factor.confidence.toFixed(1)}%
                  </span>
                  <span>
                    compl {(factor.completeness * 100).toFixed(0)}%
                  </span>
                  <span className="font-mono">
                    contrib={factor.contribution.toFixed(4)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
