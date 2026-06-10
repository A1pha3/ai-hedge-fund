/**
 * P2-5/P2-6: 选股结果展示面板 (展示型组件)。
 *
 * 渲染 ScreeningResponse.recommendations 列表 (ticker / name / score_b /
 * decision)。纯展示 — 数据由父容器 (screening-results-with-weights) 通过
 * customWeightsApi 获取后传入。对齐 risk-monitor-panel 的展示型模式。
 *
 * 字段从后端 list[dict] 宽松读取 (defensive): 缺失字段显示占位符而非崩溃。
 */
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ListOrdered } from 'lucide-react';

import type { ScreeningRecommendation } from '@/services/custom-weights-api';

export interface ScreeningResultsPanelProps {
  recommendations: ScreeningRecommendation[];
  tradeDate?: string | null;
  /** 父容器正在重新拉取时显示骨架占位。 */
  isLoading?: boolean;
  /** 空状态提示文案 (默认 "暂无推荐")。 */
  emptyHint?: string;
}

function _num(rec: ScreeningRecommendation, key: string): number | null {
  const v = rec[key];
  return typeof v === 'number' && Number.isFinite(v) ? (v as number) : null;
}

function _str(rec: ScreeningRecommendation, key: string): string {
  const v = rec[key];
  return typeof v === 'string' ? v : '';
}

function _decisionVariant(decision: string): 'success' | 'destructive' | 'secondary' {
  const d = (decision || '').toLowerCase();
  if (d.includes('bull') || d.includes('buy') || d.includes('多')) return 'success';
  if (d.includes('bear') || d.includes('sell') || d.includes('空')) return 'destructive';
  return 'secondary';
}

export function ScreeningResultsPanel({
  recommendations,
  tradeDate,
  isLoading = false,
  emptyHint = '暂无推荐 — 请先运行 --auto 生成报告',
}: ScreeningResultsPanelProps) {
  const count = recommendations.length;

  return (
    <Card className="overflow-hidden" data-testid="screening-results-panel">
      <CardHeader className="bg-muted/50 pb-3">
        <div className="flex items-center gap-2">
          <ListOrdered className="h-4 w-4 text-primary" />
          <CardTitle className="text-base">选股结果</CardTitle>
          {tradeDate && <Badge variant="outline">{tradeDate}</Badge>}
        </div>
        <CardDescription>
          {isLoading ? '重新排序中…' : `共 ${count} 只推荐 (按当前权重排序)`}
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-4">
        {count === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="screening-results-empty">
            {emptyHint}
          </p>
        ) : (
          <div className="space-y-1" data-testid="screening-results-list">
            {recommendations.map((rec, idx) => {
              const ticker = _str(rec, 'ticker') || '?';
              const name = _str(rec, 'name');
              const score = _num(rec, 'score_b');
              const decision = _str(rec, 'decision');
              return (
                <div
                  key={`${ticker}-${idx}`}
                  className="flex items-center justify-between rounded px-2 py-1.5 text-sm hover:bg-muted/40"
                  data-testid={`screening-result-row-${ticker}`}
                >
                  <div className="flex items-center gap-3">
                    <span className="w-5 text-right font-mono text-muted-foreground">{idx + 1}</span>
                    <span className="font-mono font-medium">{ticker}</span>
                    {name && <span className="text-muted-foreground">{name}</span>}
                  </div>
                  <div className="flex items-center gap-2">
                    {score !== null && (
                      <span className="font-mono" data-testid={`score-${ticker}`}>
                        {score.toFixed(1)}
                      </span>
                    )}
                    {decision && <Badge variant={_decisionVariant(decision)}>{decision}</Badge>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
