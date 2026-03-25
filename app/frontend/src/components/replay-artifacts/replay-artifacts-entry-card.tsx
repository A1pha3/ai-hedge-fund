import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ArrowRight, Database } from 'lucide-react';

interface ReplayArtifactsEntryCardProps {
  onOpen: () => void;
}

export function ReplayArtifactsEntryCard({ onOpen }: ReplayArtifactsEntryCardProps) {
  return (
    <Card className="border-border/60 bg-muted/10">
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle>Replay Artifacts</CardTitle>
            <CardDescription className="mt-2 max-w-2xl">
              Replay Artifacts 已升级为一级工作台，用于浏览 report 列表、selection artifact、funnel diagnostics、feedback 和 cache benchmark 细节。
            </CardDescription>
          </div>
          <Database className="h-5 w-5 text-muted-foreground" />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-md border border-border/60 bg-background/70 p-4">
            <p className="text-sm font-medium text-primary">Report Rail</p>
            <p className="mt-2 text-sm text-muted-foreground">按时间窗口、模型和 benchmark 状态快速筛选 replay 报告。</p>
          </div>
          <div className="rounded-md border border-border/60 bg-background/70 p-4">
            <p className="text-sm font-medium text-primary">Analysis Canvas</p>
            <p className="mt-2 text-sm text-muted-foreground">查看 KPI、selection review、Layer C 共识、research prompt 和日级诊断。</p>
          </div>
          <div className="rounded-md border border-border/60 bg-background/70 p-4">
            <p className="text-sm font-medium text-primary">Inspector</p>
            <p className="mt-2 text-sm text-muted-foreground">聚合 artifact 路径、feedback 时间线和 cache benchmark 细节，不再受 settings 内容区宽度限制。</p>
          </div>
        </div>
        <Button onClick={onOpen} className="gap-2">
          打开 Replay Artifacts 工作台
          <ArrowRight className="h-4 w-4" />
        </Button>
      </CardContent>
    </Card>
  );
}