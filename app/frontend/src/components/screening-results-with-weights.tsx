/**
 * P2-5: 选股结果 + 自定义权重 容器 (screening-results 展示面)。
 *
 * 自包含: 挂载时用默认等权调用 /api/screening/custom-weights 拉取推荐;
 * 用户调整权重 → onApply → 重新拉取 → 重渲染结果。这是剩余 P2 前端功能的
 * 共享展示面 (P2-5 权重 / P2-6 详情 / P2-2 对比 / P2-7 回放 均可挂在此面上)。
 *
 * 数据源: data/reports/auto_screening_<date>.json (经 /custom-weights 重排)。
 * 若无报告 (后端 404) → 显示错误提示 "请先运行 --auto"。
 */
import { useEffect, useState } from 'react';

import { CustomWeightsPanel } from '@/components/custom-weights-panel';
import { ScreeningResultsPanel } from '@/components/screening-results-panel';
import { customWeightsApi, type CustomWeightsRequest, type ScreeningRecommendation } from '@/services/custom-weights-api';

const DEFAULT_WEIGHTS: CustomWeightsRequest = {
  trend: 0.25,
  mean_reversion: 0.25,
  fundamental: 0.25,
  event_sentiment: 0.25,
};

export interface ScreeningResultsWithWeightsProps {
  /** 初始权重 (缺省等权 0.25)。 */
  initialWeights?: CustomWeightsRequest;
  /** 注入式 API (测试可覆盖); 缺省用真实 customWeightsApi。 */
  api?: typeof customWeightsApi;
}

export function ScreeningResultsWithWeights({
  initialWeights = DEFAULT_WEIGHTS,
  api = customWeightsApi,
}: ScreeningResultsWithWeightsProps) {
  const [recommendations, setRecommendations] = useState<ScreeningRecommendation[]>([]);
  const [tradeDate, setTradeDate] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchWithWeights = async (weights: CustomWeightsRequest) => {
    setIsLoading(true);
    setError(null);
    try {
      const resp = await api.apply(weights);
      setRecommendations(resp.recommendations);
      setTradeDate(resp.trade_date);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      setRecommendations([]);
    } finally {
      setIsLoading(false);
    }
  };

  // 挂载时拉取初始 (等权) 推荐
  useEffect(() => {
    fetchWithWeights(initialWeights);
    // 仅挂载时执行一次 (initialWeights 由父组件控制, 不在运行时变)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleApply = (weights: CustomWeightsRequest) => {
    fetchWithWeights(weights);
  };

  return (
    <div className="space-y-4" data-testid="screening-results-with-weights">
      <CustomWeightsPanel
        initialWeights={initialWeights}
        onApply={handleApply}
        isApplying={isLoading}
        errorMessage={error}
      />
      <ScreeningResultsPanel
        recommendations={recommendations}
        tradeDate={tradeDate}
        isLoading={isLoading}
      />
    </div>
  );
}
