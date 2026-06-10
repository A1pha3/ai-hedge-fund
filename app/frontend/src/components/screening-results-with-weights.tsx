/**
 * P2-5/P2-6: 选股结果 + 自定义权重 + 标的详情 容器 (screening-results 展示面)。
 *
 * 自包含: 挂载时用默认等权调用 /api/screening/custom-weights 拉取推荐;
 * 用户调整权重 → onApply → 重新拉取 → 重渲染结果。
 * 点击推荐行 → 拉取 /api/screening/stock-detail/{ticker} → 展示详情卡。
 *
 * 数据源: data/reports/auto_screening_<date>.json (经 /custom-weights 重排)。
 * 若无报告 (后端 404) → 显示错误提示 "请先运行 --auto"。
 */
import { useCallback, useEffect, useState } from 'react';

import { CustomWeightsPanel } from '@/components/custom-weights-panel';
import { ScreeningResultsPanel } from '@/components/screening-results-panel';
import { StockDetailCard } from '@/components/stock-detail-card';
import { customWeightsApi, type CustomWeightsRequest, type ScreeningRecommendation } from '@/services/custom-weights-api';
import { stockDetailApi, type StockDetail } from '@/services/stock-detail-api';

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
  /** 注入式 stock detail API (测试可覆盖)。 */
  detailApi?: typeof stockDetailApi;
}

export function ScreeningResultsWithWeights({
  initialWeights = DEFAULT_WEIGHTS,
  api = customWeightsApi,
  detailApi = stockDetailApi,
}: ScreeningResultsWithWeightsProps) {
  const [recommendations, setRecommendations] = useState<ScreeningRecommendation[]>([]);
  const [tradeDate, setTradeDate] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // P2-6: 标的详情状态
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [stockDetail, setStockDetail] = useState<StockDetail | null>(null);
  const [isDetailLoading, setIsDetailLoading] = useState(false);

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

  // P2-6: 点击推荐行 → 拉取详情
  const handleSelectTicker = useCallback(async (ticker: string) => {
    if (ticker === selectedTicker) {
      // 再次点击同一行 → 关闭详情
      setSelectedTicker(null);
      setStockDetail(null);
      return;
    }
    setSelectedTicker(ticker);
    setIsDetailLoading(true);
    setStockDetail(null);
    try {
      const detail = await detailApi.fetch(ticker);
      setStockDetail(detail);
    } catch {
      // 后端 404 / 无数据 → 显示空详情卡 (用户看到 '—' 占位)
      setStockDetail(null);
    } finally {
      setIsDetailLoading(false);
    }
  }, [selectedTicker, detailApi]);

  const handleCloseDetail = useCallback(() => {
    setSelectedTicker(null);
    setStockDetail(null);
  }, []);

  return (
    <div className="space-y-4" data-testid="screening-results-with-weights">
      <CustomWeightsPanel
        initialWeights={initialWeights}
        onApply={handleApply}
        isApplying={isLoading}
        errorMessage={error}
      />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ScreeningResultsPanel
          recommendations={recommendations}
          tradeDate={tradeDate}
          isLoading={isLoading}
          onSelectTicker={handleSelectTicker}
          selectedTicker={selectedTicker}
        />
        {/* P2-6: 详情卡 — 仅选中时显示 */}
        {selectedTicker && (
          <StockDetailCard
            detail={stockDetail}
            isLoading={isDetailLoading}
            onClose={handleCloseDetail}
          />
        )}
      </div>
    </div>
  );
}
