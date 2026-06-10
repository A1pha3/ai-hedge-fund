/**
 * P2-6: 标的深度分析卡片 (展示型组件)。
 *
 * 展示单只推荐标的的全维度分析:
 *   - 基本面 (PE / PB / ROE / 营收增长 / 利润增长 / 股息率)
 *   - 技术面 (价格 / 涨跌幅 / 均线 / RSI / MACD / ATR)
 *   - 资金面 (主力净流入 / 北向资金 / 龙虎榜)
 *   - 系统历史 (推荐次数 / 连续天数 / 信号衰减 / 行业排名)
 *
 * 纯展示组件 — 数据由父组件通过 stockDetailApi.fetch() 获取后传入。
 * 对齐 custom-weights-panel / screening-results-panel 的展示型模式。
 */
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ArrowDown, ArrowUp, BarChart3, DollarSign, LineChart, Activity } from 'lucide-react';

import type { StockDetail } from '@/services/stock-detail-api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** 安全格式化百分比 (null → '—')。 */
function _pct(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${(v * 100).toFixed(digits)}%`;
}

/** 安全格式化数值 (null → '—')。 */
function _num(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return v.toFixed(digits);
}

/** 安全格式化整数 (null → '—')。 */
function _int(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return String(Math.round(v));
}

/** 涨跌幅颜色 + 箭头。 */
function _changeEl(pct: number): React.ReactNode {
  if (pct > 0) return <span className="text-red-500"><ArrowUp className="inline h-3 w-3" />{pct.toFixed(2)}%</span>;
  if (pct < 0) return <span className="text-green-600"><ArrowDown className="inline h-3 w-3" />{Math.abs(pct).toFixed(2)}%</span>;
  return <span>{pct.toFixed(2)}%</span>;
}

/** 指标行组件。 */
function _MetricRow({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between py-1 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={highlight ? 'font-medium' : 'font-mono'}>{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Props & Component
// ---------------------------------------------------------------------------

export interface StockDetailCardProps {
  /** 标的深度分析数据 (来自 stockDetailApi.fetch)。 */
  detail: StockDetail | null;
  /** 加载中。 */
  isLoading?: boolean;
  /** 关闭回调。 */
  onClose: () => void;
}

export function StockDetailCard({ detail, isLoading = false, onClose }: StockDetailCardProps) {
  if (isLoading) {
    return (
      <Card className="overflow-hidden" data-testid="stock-detail-card">
        <CardHeader className="bg-muted/50 pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Skeleton className="h-4 w-4" />
              <Skeleton className="h-5 w-32" />
            </div>
            <button onClick={onClose} className="text-sm text-muted-foreground hover:text-foreground" data-testid="stock-detail-close">✕</button>
          </div>
          <Skeleton className="h-4 w-48" />
        </CardHeader>
        <CardContent className="pt-4 space-y-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!detail) return null;

  const d = detail;

  return (
    <Card className="overflow-hidden" data-testid="stock-detail-card">
      {/* ── Header ── */}
      <CardHeader className="bg-muted/50 pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-primary" />
            <CardTitle className="text-base">
              {d.ticker}
              {d.name && <span className="ml-2 text-muted-foreground font-normal">{d.name}</span>}
            </CardTitle>
          </div>
          <button onClick={onClose} className="text-sm text-muted-foreground hover:text-foreground" data-testid="stock-detail-close">✕</button>
        </div>
        <CardDescription className="flex items-center gap-3">
          <span className="font-mono text-foreground">¥{_num(d.price)}</span>
          {_changeEl(d.change_pct)}
          {d.industry_sw && <Badge variant="outline">{d.industry_sw}</Badge>}
        </CardDescription>
      </CardHeader>

      {/* ── Tabs: 基本面 / 技术面 / 资金面 / 系统历史 ── */}
      <CardContent className="pt-2">
        <Tabs defaultValue="fundamental" className="w-full">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="fundamental" className="text-xs">
              <DollarSign className="mr-1 h-3 w-3" />基本面
            </TabsTrigger>
            <TabsTrigger value="technical" className="text-xs">
              <LineChart className="mr-1 h-3 w-3" />技术面
            </TabsTrigger>
            <TabsTrigger value="money" className="text-xs">
              <Activity className="mr-1 h-3 w-3" />资金面
            </TabsTrigger>
            <TabsTrigger value="history" className="text-xs">
              <BarChart3 className="mr-1 h-3 w-3" />历史
            </TabsTrigger>
          </TabsList>

          {/* ── Tab 1: 基本面 ── */}
          <TabsContent value="fundamental" className="mt-3 space-y-1">
            <_MetricRow label="PE (市盈率)" value={_num(d.pe_ratio)} />
            <_MetricRow label="PB (市净率)" value={_num(d.pb_ratio)} />
            <_MetricRow label="ROE (净资产收益率)" value={_pct(d.roe)} highlight />
            <_MetricRow label="营收增长率" value={_pct(d.revenue_growth)} />
            <_MetricRow label="利润增长率" value={_pct(d.profit_growth)} />
            <_MetricRow label="股息率" value={_pct(d.dividend_yield)} />
          </TabsContent>

          {/* ── Tab 2: 技术面 ── */}
          <TabsContent value="technical" className="mt-3 space-y-1">
            <_MetricRow label="MA5" value={_num(d.ma5)} />
            <_MetricRow label="MA20" value={_num(d.ma20)} />
            <_MetricRow label="MA60" value={_num(d.ma60)} />
            <Separator className="my-1" />
            <_MetricRow label="RSI (14)" value={_num(d.rsi_14)} highlight />
            <_MetricRow
              label="MACD 信号"
              value={d.macd_signal || '—'}
            />
            <_MetricRow label="ATR (%)" value={_pct(d.atr_pct)} />
          </TabsContent>

          {/* ── Tab 3: 资金面 ── */}
          <TabsContent value="money" className="mt-3 space-y-1">
            <_MetricRow label="主力净流入" value={d.money_flow_net != null ? `${(d.money_flow_net / 1e8).toFixed(2)}亿` : '—'} highlight />
            <_MetricRow label="北向资金" value={d.north_money_net != null ? `${(d.north_money_net / 1e8).toFixed(2)}亿` : '—'} />
            <_MetricRow
              label="龙虎榜"
              value={d.dragon_tiger ? '✓ 上榜' : '—'}
              highlight={d.dragon_tiger}
            />
          </TabsContent>

          {/* ── Tab 4: 系统历史 ── */}
          <TabsContent value="history" className="mt-3 space-y-1">
            <_MetricRow label="近 30 天推荐次数" value={_int(d.recommendation_count_30d)} highlight />
            <_MetricRow label="最新 Score B" value={_num(d.latest_score_b, 4)} highlight />
            <_MetricRow
              label="最新决策"
              value={d.latest_decision || '—'}
            />
            <Separator className="my-1" />
            <_MetricRow
              label="连续推荐天数"
              value={_int(d.consecutive_days)}
              highlight={d.consecutive_days >= 3}
            />
            <_MetricRow
              label="信号衰减"
              value={d.decay_level || '—'}
            />
            <Separator className="my-1" />
            <_MetricRow
              label="行业排名"
              value={d.industry_rank != null && d.industry_total != null ? `${d.industry_rank}/${d.industry_total}` : '—'}
              highlight
            />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
