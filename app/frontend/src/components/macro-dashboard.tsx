/**
 * P2-9: 宏观经济仪表盘 (展示型组件)。
 *
 * 展示当前宏观经济环境快照:
 *   - 6 个核心指标 (CPI / PPI / PMI / M2 / 社融 / LPR)
 *   - 3 个派生标签 (通胀压力 / 货币立场 / 经济动能)
 *   - 数据日期
 *
 * 纯展示组件 — 数据由父组件通过 macroApi.fetch() 获取后传入。
 * 对齐 stock-detail-card / param-compare-panel 展示型模式。
 */
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Globe } from 'lucide-react';

import {
  MACRO_LABELS,
  formatMacroValue,
  regimeVariant,
  regimeChinese,
  REGIME_LABELS,
  type MacroSnapshot,
} from '@/services/macro-snapshot-api';

// ---------------------------------------------------------------------------
// Metric row
// ---------------------------------------------------------------------------

function _MetricRow({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="flex items-center justify-between py-1 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono">
        {value}
        {unit && <span className="ml-0.5 text-xs text-muted-foreground">{unit}</span>}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Regime badges
// ---------------------------------------------------------------------------

const REGIME_KEYS = ['inflation_pressure', 'monetary_stance', 'economic_momentum'] as const;

// ---------------------------------------------------------------------------
// Props & Component
// ---------------------------------------------------------------------------

export interface MacroDashboardProps {
  /** 宏观快照数据。 */
  snapshot: MacroSnapshot | null;
  /** 是否正在加载。 */
  isLoading?: boolean;
}

export function MacroDashboard({ snapshot, isLoading = false }: MacroDashboardProps) {
  if (isLoading) {
    return (
      <Card className="overflow-hidden" data-testid="macro-dashboard">
        <CardHeader className="bg-muted/50 pb-3">
          <div className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-primary" />
            <CardTitle className="text-base">宏观经济</CardTitle>
          </div>
          <CardDescription>加载中…</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (!snapshot) {
    return (
      <Card className="overflow-hidden" data-testid="macro-dashboard">
        <CardHeader className="bg-muted/50 pb-3">
          <div className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-primary" />
            <CardTitle className="text-base">宏观经济</CardTitle>
          </div>
          <CardDescription>暂无宏观数据 — 需要 tushare 数据源</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const metrics: { key: keyof typeof MACRO_LABELS; raw: number | null }[] = [
    { key: 'cpi_yoy', raw: snapshot.cpi_yoy },
    { key: 'ppi_yoy', raw: snapshot.ppi_yoy },
    { key: 'pmi_manufacturing', raw: snapshot.pmi_manufacturing },
    { key: 'pmi_non_manufacturing', raw: snapshot.pmi_non_manufacturing },
    { key: 'm2_yoy', raw: snapshot.m2_yoy },
    { key: 'social_financing', raw: snapshot.social_financing },
    { key: 'interest_rate_lpr_1y', raw: snapshot.interest_rate_lpr_1y },
  ];

  return (
    <Card className="overflow-hidden" data-testid="macro-dashboard">
      <CardHeader className="bg-muted/50 pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-primary" />
            <CardTitle className="text-base">宏观经济环境</CardTitle>
          </div>
          {snapshot.date && <Badge variant="outline">{snapshot.date}</Badge>}
        </div>
        <CardDescription>最新宏观经济指标 + 市场环境判断</CardDescription>
      </CardHeader>
      <CardContent className="pt-4 space-y-3">
        {/* ── 派生标签 ── */}
        <div className="flex flex-wrap gap-2" data-testid="macro-regime-badges">
          {REGIME_KEYS.map((key) => {
            const value = snapshot[key] as string;
            return (
              <div key={key} className="flex items-center gap-1 text-xs">
                <span className="text-muted-foreground">{REGIME_LABELS[key]}:</span>
                <Badge variant={regimeVariant(value)}>
                  {regimeChinese(value)}
                </Badge>
              </div>
            );
          })}
        </div>

        {/* ── 指标列表 ── */}
        <div className="space-y-0.5" data-testid="macro-metrics">
          {metrics.map(({ key, raw }) => (
            <_MetricRow
              key={key}
              label={MACRO_LABELS[key]}
              value={formatMacroValue(key, raw)}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
