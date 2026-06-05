import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { AlertCircle, ArrowDown, ArrowUp, CheckCircle2, Minus, ShieldAlert } from 'lucide-react';

import type { BtstDecisionCardData } from './types';

interface BtstDecisionCardProps {
  data: BtstDecisionCardData | null | undefined;
  /** 关联主票当日收盘价（用于计算建议股数） */
  currentPrice?: number | null;
  /** 投资组合 NAV（用于仓位百分比展示） */
  portfolioNav?: number | null;
}

/**
 * P0 1.4 — BTST 决策卡。
 *
 * 把 `decision_card` 字典渲染成"行动 + 仓位 + 风险"三段卡片。
 * 决策卡 = 操作员一眼看完 5 秒内就要 BUY / HOLD / SELL。
 */
export function BtstDecisionCard({ data, currentPrice, portfolioNav }: BtstDecisionCardProps) {
  if (!data) {
    return (
      <Card className="border-dashed">
        <CardHeader>
          <CardTitle className="text-base">BTST 决策卡</CardTitle>
          <CardDescription>
            当前 run 未提供 <code>btst_decision_card</code> 字段。需要先在
            <code> outputNodeData</code> 注入决策卡或后端补一个聚合 API。
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const action = (data.trade_bias || 'skip').toLowerCase();
  const actionMeta = resolveActionMeta(action);
  const gradeMeta = resolveGradeMeta(data.evidence_grade);
  const dataQualityMeta = resolveDataQualityMeta(data.data_quality);
  const riskMeta = resolveRiskPostureMeta(data.risk_posture);

  // 仓位建议
  const positionScale = data.position_scale;
  const suggestedAmount =
    positionScale !== null && positionScale !== undefined && portfolioNav
      ? (portfolioNav * positionScale) / 100
      : null;
  const suggestedShares =
    suggestedAmount !== null && currentPrice && currentPrice > 0
      ? Math.floor(suggestedAmount / currentPrice)
      : null;

  return (
    <Card className="overflow-hidden">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            {actionMeta.icon}
            BTST 决策卡 — {data.signal_date || 'n/a'}
          </CardTitle>
          <Badge variant={actionMeta.badgeVariant}>{actionMeta.label}</Badge>
        </div>
        <CardDescription>
          {data.primary_ticker ? (
            <>
              主票 <span className="font-mono font-semibold">{data.primary_ticker}</span>
              {data.primary_name ? ` (${data.primary_name})` : ''} · 下一交易日{' '}
              {data.next_trade_date || 'n/a'}
            </>
          ) : (
            '无可执行主票（保持空仓观察）。'
          )}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* 顶部 4 个量化指标 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Metric label="行动 (Trade Bias)" value={actionMeta.label} accent={actionMeta.textClass} />
          <Metric
            label="证据等级 (Evidence Grade)"
            value={gradeMeta.label}
            accent={gradeMeta.textClass}
            hint={gradeMeta.hint}
          />
          <Metric
            label="数据质量"
            value={dataQualityMeta.label}
            accent={dataQualityMeta.textClass}
          />
          <Metric
            label="风险姿态"
            value={riskMeta.label}
            accent={riskMeta.textClass}
            hint={riskMeta.hint}
          />
        </div>

        {/* 仓位建议 */}
        <div className="rounded-md border border-border/60 bg-muted/20 p-3 space-y-1">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            仓位建议 (Position Sizing)
          </p>
          {positionScale !== null && positionScale !== undefined ? (
            <>
              <p className="text-lg font-semibold text-foreground">
                {positionScale.toFixed(1)}% NAV
                {suggestedAmount !== null && (
                  <span className="ml-2 text-sm text-muted-foreground font-normal">
                    ≈ ¥{suggestedAmount.toFixed(0)}
                  </span>
                )}
                {suggestedShares !== null && currentPrice && (
                  <span className="ml-2 text-sm text-muted-foreground font-normal">
                    · {suggestedShares} 股 @ ¥{currentPrice.toFixed(2)}
                  </span>
                )}
              </p>
              <p className="text-xs text-muted-foreground">
                {portfolioNav
                  ? `基于 NAV ¥${portfolioNav.toFixed(0)} 估算，实际下单按当日本金 0.5×/1.0× 调整。`
                  : 'NAV 未提供，按 100w NAV 默认估算。'}
              </p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              仓位百分比未提供——保守解读：模型未给出明确建议。
            </p>
          )}
        </div>

        {/* must_confirm / invalidate_if 双栏 */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Note
            tone="confirm"
            title="必须盘中确认 (Must Confirm)"
            text={data.must_confirm}
            fallback="无明确必确认条件。"
          />
          <Note
            tone="invalidate"
            title="失效条件 (Invalidate If)"
            text={data.invalidate_if}
            fallback="未指定失效条件。"
          />
        </div>

        {data.early_runner_status && (
          <p className="text-xs text-muted-foreground">
            Early Runner 状态:{' '}
            <span className="font-mono">{data.early_runner_status}</span>
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Metric({
  label,
  value,
  accent,
  hint,
}: {
  label: string;
  value: string;
  accent?: string;
  hint?: string;
}) {
  return (
    <div className="rounded-md border border-border/40 bg-background p-3 space-y-1">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`text-base font-semibold ${accent ?? 'text-foreground'}`}>{value}</p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Note({
  tone,
  title,
  text,
  fallback,
}: {
  tone: 'confirm' | 'invalidate';
  title: string;
  text: string | null | undefined;
  fallback: string;
}) {
  const isConfirm = tone === 'confirm';
  const Icon = isConfirm ? CheckCircle2 : ShieldAlert;
  return (
    <div
      className={`rounded-md border p-3 space-y-1 ${
        isConfirm
          ? 'border-green-500/30 bg-green-500/5'
          : 'border-red-500/30 bg-red-500/5'
      }`}
    >
      <p
        className={`text-xs uppercase tracking-wide flex items-center gap-1 ${
          isConfirm ? 'text-green-700 dark:text-green-400' : 'text-red-700 dark:text-red-400'
        }`}
      >
        <Icon className="h-3 w-3" />
        {title}
      </p>
      <p className="text-sm leading-relaxed text-foreground">
        {text && text.trim() ? text : fallback}
      </p>
    </div>
  );
}

// ---------- metadata resolvers ----------

type Meta<TBadge extends string> = {
  label: string;
  textClass: string;
  badgeVariant: TBadge;
  icon: JSX.Element;
  hint?: string;
};

function resolveActionMeta(action: string): Meta<'destructive' | 'success' | 'warning' | 'outline'> {
  switch (action) {
    case 'buy':
    case 'trade_allowed':
    case 'long':
      return {
        label: 'BUY',
        textClass: 'text-green-600 dark:text-green-400',
        badgeVariant: 'success',
        icon: <ArrowUp className="h-4 w-4 text-green-500" />,
      };
    case 'sell':
    case 'short':
      return {
        label: 'SELL',
        textClass: 'text-red-600 dark:text-red-400',
        badgeVariant: 'destructive',
        icon: <ArrowDown className="h-4 w-4 text-red-500" />,
      };
    case 'confirmation_only':
    case 'confirm':
      return {
        label: 'CONFIRM',
        textClass: 'text-yellow-600 dark:text-yellow-400',
        badgeVariant: 'warning',
        icon: <AlertCircle className="h-4 w-4 text-yellow-500" />,
      };
    case 'hold':
      return {
        label: 'HOLD',
        textClass: 'text-yellow-600 dark:text-yellow-400',
        badgeVariant: 'warning',
        icon: <Minus className="h-4 w-4 text-yellow-500" />,
      };
    case 'skip':
    case 'no_trade':
    default:
      return {
        label: 'SKIP',
        textClass: 'text-muted-foreground',
        badgeVariant: 'outline',
        icon: <Minus className="h-4 w-4 text-muted-foreground" />,
      };
  }
}

function resolveGradeMeta(grade: string | null | undefined) {
  switch ((grade || '').toUpperCase()) {
    case 'A':
      return { label: 'A', textClass: 'text-green-600 dark:text-green-400', hint: '高质量证据' };
    case 'B':
      return { label: 'B', textClass: 'text-blue-600 dark:text-blue-400', hint: '可执行' };
    case 'C':
      return { label: 'C', textClass: 'text-yellow-600 dark:text-yellow-400', hint: '需复盘' };
    case 'D':
    default:
      return { label: 'D', textClass: 'text-red-600 dark:text-red-400', hint: '不建议开仓' };
  }
}

function resolveDataQualityMeta(q: string | null | undefined) {
  switch ((q || '').toLowerCase()) {
    case 'sufficient':
    case 'high':
      return { label: '充足', textClass: 'text-green-600 dark:text-green-400' };
    case 'partial':
    case 'medium':
      return { label: '部分', textClass: 'text-yellow-600 dark:text-yellow-400' };
    case 'insufficient':
    case 'low':
    default:
      return { label: '不足', textClass: 'text-red-600 dark:text-red-400' };
  }
}

function resolveRiskPostureMeta(p: string | null | undefined) {
  switch ((p || '').toLowerCase()) {
    case 'aggressive':
      return { label: '激进', textClass: 'text-red-600 dark:text-red-400', hint: '允许放仓位' };
    case 'standard':
      return { label: '标准', textClass: 'text-blue-600 dark:text-blue-400' };
    case 'conservative':
      return { label: '保守', textClass: 'text-yellow-600 dark:text-yellow-400', hint: '建议减半仓位' };
    case 'no_trade':
    default:
      return { label: '禁开仓', textClass: 'text-muted-foreground', hint: '保持空仓' };
  }
}
