/**
 * P2-5: 自定义策略权重面板 (展示型组件)。
 *
 * 让用户用 4 个滑块调整策略权重 (trend / mean_reversion / fundamental /
 * event_sentiment), 实时校验权重和 ≈ 1.0, 点击「应用」回调父组件。
 *
 * 纯展示组件 — 不直接调用 API (对齐 risk-monitor-panel 模式: 父组件负责
 * fetch + state)。父组件在 onApply 回调里调用 `customWeightsApi.apply()`。
 *
 * 用原生 <input type="range"> 避免引入 shadcn Slider 依赖 (项目暂无该原语)。
 */
import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Scale } from 'lucide-react';

import { sumWeights, type CustomWeightsRequest } from '@/services/custom-weights-api';

type WeightKey = 'trend' | 'mean_reversion' | 'fundamental' | 'event_sentiment';

const STRATEGY_FIELDS: { key: WeightKey; label: string }[] = [
  { key: 'trend', label: '趋势' },
  { key: 'mean_reversion', label: '均值回归' },
  { key: 'fundamental', label: '基本面' },
  { key: 'event_sentiment', label: '事件情绪' },
];

const EQUAL_WEIGHTS: Record<WeightKey, number> = {
  trend: 0.25,
  mean_reversion: 0.25,
  fundamental: 0.25,
  event_sentiment: 0.25,
};

export interface CustomWeightsPanelProps {
  /** 点击「应用」时回调, 传入当前 4 权重 (已校验和 ≈ 1.0)。 */
  onApply: (weights: CustomWeightsRequest) => void;
  /** 初始权重 (缺省 = 各 0.25)。 */
  initialWeights?: Partial<Record<WeightKey, number>>;
  /** 是否正在提交 (禁用按钮 + 显示「应用中…」)。 */
  isApplying?: boolean;
  /** 父组件透传的错误信息 (如后端 422/404)。 */
  errorMessage?: string | null;
}

export function CustomWeightsPanel({
  onApply,
  initialWeights,
  isApplying = false,
  errorMessage = null,
}: CustomWeightsPanelProps) {
  const [weights, setWeights] = useState<Record<WeightKey, number>>({
    ...EQUAL_WEIGHTS,
    ...(initialWeights as Record<WeightKey, number>),
  });

  const sum = sumWeights(weights);
  // 与后端 sum==1.0 ±1e-6 一致
  const valid = Math.abs(sum - 1.0) < 1e-6;

  const handleChange = (key: WeightKey, raw: string) => {
    const value = Number.parseFloat(raw);
    if (Number.isFinite(value)) {
      setWeights((prev) => ({ ...prev, [key]: value }));
    }
  };

  const handleApply = () => {
    if (!valid || isApplying) return;
    onApply({ ...weights });
  };

  return (
    <Card className="overflow-hidden" data-testid="custom-weights-panel">
      <CardHeader className="bg-muted/50 pb-3">
        <div className="flex items-center gap-2">
          <Scale className="h-4 w-4 text-primary" />
          <CardTitle className="text-base">自定义策略权重</CardTitle>
        </div>
        <CardDescription>调整 4 个策略权重 (之和需 = 1.00), 按新权重重新排序推荐</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 pt-4">
        {STRATEGY_FIELDS.map(({ key, label }) => (
          <div key={key} className="space-y-1">
            <div className="flex justify-between text-sm">
              <span>{label}</span>
              <span className="font-mono" data-testid={`weight-value-${key}`}>
                {weights[key].toFixed(2)}
              </span>
            </div>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={weights[key]}
              onChange={(e) => handleChange(key, e.target.value)}
              aria-label={`${label}权重`}
              data-testid={`weight-${key}`}
              className="w-full accent-primary"
            />
          </div>
        ))}

        <div className="flex items-center justify-between">
          <Badge variant={valid ? 'success' : 'destructive'} data-testid="weight-sum">
            权重和: {sum.toFixed(2)}
            {valid ? '' : ' (需=1.00)'}
          </Badge>
          <Button onClick={handleApply} disabled={!valid || isApplying} data-testid="weight-apply">
            {isApplying ? '应用中…' : '应用权重'}
          </Button>
        </div>

        {errorMessage && (
          <p className="text-sm text-destructive" data-testid="weight-error">
            {errorMessage}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
