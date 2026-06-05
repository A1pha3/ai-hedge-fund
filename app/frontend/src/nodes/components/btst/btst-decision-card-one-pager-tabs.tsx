import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useState } from 'react';

import { BtstDecisionCard } from './btst-decision-card';
import { BtstOnePager } from './btst-one-pager';
import type { BtstPanelData } from './types';
interface BtstDecisionCardOnePagerTabsProps {
  data: BtstPanelData;
  /** 主票当日收盘价 (传给 decision card 做仓位估算) */
  primaryPrice?: number | null;
  /** 投资组合 NAV (传给 decision card 做仓位估算) */
  portfolioNav?: number | null;
  /** "展开源文档"点击回调 (由父组件实现，跳到 replay-artifacts-inspector 对应锚点) */
  onOpenSourceDoc?: (sourceDoc: string) => void;
}

type View = 'decision-card' | 'one-pager';

/**
 * P0 1.4 — BTST 决策卡 ↔ ONE-PAGER 双重消费入口。
 *
 * 一份 `BtstPanelData` (决策卡 + 8 行主问题)，两个视图，用户在不离开当前页面的
 * 情况下通过 Tab 切换。共用同一份底层数据，切换零拷贝、零网络。
 */
export function BtstDecisionCardOnePagerTabs({
  data,
  primaryPrice,
  portfolioNav,
  onOpenSourceDoc,
}: BtstDecisionCardOnePagerTabsProps) {
  // 默认显示决策卡（操作员盘前最关心的是"该不该买"）
  const [view, setView] = useState<View>('decision-card');

  // 都没有数据时不渲染
  if (!data || (!data.decision_card && !data.one_pager)) {
    return (
      <Card className="border-dashed">
        <CardHeader>
          <CardTitle className="text-base">BTST 决策卡 / ONE-PAGER</CardTitle>
          <CardDescription>
            本次 run 既无 <code>btst_decision_card</code> 也无 <code>btst_one_pager</code> 字段——
            盘前消费入口不可用。
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div data-testid="btst-panel" data-active-view={view}>
      <Tabs value={view} onValueChange={(v) => setView(v as View)}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold m-0">BTST 决策卡 / ONE-PAGER</h2>
          <TabsList>
            <TabsTrigger value="decision-card" data-testid="btst-tab-decision-card">
              决策卡
            </TabsTrigger>
            <TabsTrigger value="one-pager" data-testid="btst-tab-one-pager">
              ONE-PAGER ({data.one_pager?.questions?.length ?? 0})
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="decision-card">
          <BtstDecisionCard
            data={data.decision_card}
            currentPrice={primaryPrice}
            portfolioNav={portfolioNav}
          />
        </TabsContent>

        <TabsContent value="one-pager">
          <BtstOnePager data={data.one_pager} onOpenSourceDoc={onOpenSourceDoc} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
