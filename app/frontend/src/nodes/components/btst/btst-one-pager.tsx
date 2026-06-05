import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { AlertTriangle, CheckCircle2, FileText, Info, ShieldAlert } from 'lucide-react';

import type { BtstOnePagerData, BtstOnePagerQuestion } from './types';

interface BtstOnePagerProps {
  data: BtstOnePagerData | null | undefined;
  /** 触发"展开源文档"动作（可由父组件在打开 inspector 时实现） */
  onOpenSourceDoc?: (sourceDoc: string) => void;
}

/**
 * P0 1.4 — BTST ONE-PAGER 8 行主问题。
 *
 * 固定 8 张卡（市场状态 / 主票 / 早盘 runner / 风控门 / 仓位 / 必确认 / 失效条件 / 复盘提示），
 * 每张卡可点击"展开源文档"链接跳到对应长文档。
 */
const STATUS_META: Record<
  string,
  { label: string; icon: JSX.Element; badgeVariant: 'success' | 'warning' | 'destructive' | 'outline' }
> = {
  ok: { label: 'OK', icon: <CheckCircle2 className="h-3 w-3" />, badgeVariant: 'success' },
  warn: { label: 'WARN', icon: <AlertTriangle className="h-3 w-3" />, badgeVariant: 'warning' },
  alert: { label: 'ALERT', icon: <ShieldAlert className="h-3 w-3" />, badgeVariant: 'destructive' },
  info: { label: 'INFO', icon: <Info className="h-3 w-3" />, badgeVariant: 'outline' },
};

export function BtstOnePager({ data, onOpenSourceDoc }: BtstOnePagerProps) {
  if (!data) {
    return (
      <Card className="border-dashed">
        <CardHeader>
          <CardTitle className="text-base">BTST ONE-PAGER</CardTitle>
          <CardDescription>
            当前 run 未提供 <code>btst_one_pager</code> 字段。
            期望后端在 <code>outputNodeData.btst_one_pager</code> 注入 8 个固定问题，
            或前端从 <code>operator_summary.json</code> + 7 份文档自行组装。
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const questions = data.questions || [];
  if (questions.length === 0) {
    return (
      <Card className="border-dashed">
        <CardHeader>
          <CardTitle className="text-base">BTST ONE-PAGER</CardTitle>
          <CardDescription>
            8 行主问题为空——检查后端聚合逻辑是否漏掉了 btst.premarket_questions / 7 份文档的解析。
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">BTST ONE-PAGER</CardTitle>
          <Badge variant="outline">{questions.length} 个主问题</Badge>
        </div>
        <CardDescription>
          {data.signal_date || 'n/a'} → {data.next_trade_date || 'n/a'}
          {data.headline ? <span className="ml-2 text-foreground">{data.headline}</span> : null}
        </CardDescription>
      </CardHeader>

      <CardContent>
        <ol className="space-y-2 list-none p-0 m-0">
          {questions.map((q, idx) => (
            <QuestionRow
              key={`${q.title}-${idx}`}
              index={idx + 1}
              question={q}
              onOpenSourceDoc={onOpenSourceDoc}
            />
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

function QuestionRow({
  index,
  question,
  onOpenSourceDoc,
}: {
  index: number;
  question: BtstOnePagerQuestion;
  onOpenSourceDoc?: (sourceDoc: string) => void;
}) {
  const statusKey = (question.status || 'info').toLowerCase();
  const statusMeta = STATUS_META[statusKey] || STATUS_META.info;

  return (
    <li className="rounded-md border border-border/40 bg-muted/10 p-3 hover:bg-muted/20 transition-colors">
      <div className="flex items-start gap-3">
        <span className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-mono font-semibold flex items-center justify-center">
          {index}
        </span>

        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h4 className="text-sm font-semibold text-foreground">{question.title}</h4>
            <Badge variant={statusMeta.badgeVariant} className="gap-1">
              {statusMeta.icon}
              {statusMeta.label}
            </Badge>
          </div>
          {question.answer && (
            <p className="text-sm text-foreground leading-relaxed">{question.answer}</p>
          )}
          {question.detail && (
            <p className="text-xs text-muted-foreground leading-relaxed">
              {question.detail}
            </p>
          )}

          {question.source_doc && (
            <div className="pt-1">
              <Button
                variant="link"
                size="sm"
                className="h-auto p-0 text-xs"
                onClick={() => onOpenSourceDoc?.(question.source_doc!)}
              >
                <FileText className="h-3 w-3 mr-1" />
                展开源文档 — {question.source_doc}
              </Button>
            </div>
          )}
        </div>
      </div>
    </li>
  );
}
