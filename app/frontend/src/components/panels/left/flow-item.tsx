import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useNodeContext } from '@/contexts/node-context';
import { useFlowConnectionState } from '@/hooks/use-flow-connection';
import { cn } from '@/lib/utils';
import { api } from '@/services/api';
import { flowService, FlowRunSummary } from '@/services/flow-service';
import { Flow } from '@/types/flow';
import {
  Calendar,
  FileText,
  Layout,
  MoreHorizontal,
  Zap
} from 'lucide-react';
import { useState, useEffect } from 'react';
import { FlowContextMenu } from './flow-context-menu';
import { FlowEditDialog } from './flow-edit-dialog';
import { flowConnectionManager } from '@/hooks/use-flow-connection';

interface FlowItemProps {
  flow: Flow;
  onLoadFlow: (flow: Flow) => Promise<void>;
  onDeleteFlow: (flow: Flow) => Promise<void>;
  onRefresh: () => Promise<void>;
  isActive?: boolean;
}

function isRerunGraphNode(node: unknown): node is { id: string } {
  return typeof node === 'object' && node !== null && 'id' in node && typeof node.id === 'string';
}

function resolveRerunGraphNodes(
  requestData: Record<string, unknown> | null | undefined,
  fallbackNodes: Array<{ id: string }>,
): Array<{ id: string }> {
  const graphNodes = requestData?.graph_nodes;
  if (!Array.isArray(graphNodes)) {
    return fallbackNodes.map(({ id }) => ({ id }));
  }

  const historicalNodes = graphNodes.filter(isRerunGraphNode).map(({ id }) => ({ id }));
  return historicalNodes.length > 0 ? historicalNodes : fallbackNodes.map(({ id }) => ({ id }));
}

export default function FlowItem({ flow, onLoadFlow, onDeleteFlow, onRefresh, isActive = false }: FlowItemProps) {
  const nodeContext = useNodeContext();
  const [contextMenu, setContextMenu] = useState<{ isOpen: boolean; position: { x: number; y: number } }>({
    isOpen: false,
    position: { x: 0, y: 0 }
  });
  const [editDialog, setEditDialog] = useState(false);
  const [hasCompletedRuns, setHasCompletedRuns] = useState(false);
  const [latestRunId, setLatestRunId] = useState<number | null>(null);

  // Check if this flow has an active connection
  const connectionState = useFlowConnectionState(flow.id.toString());
  const hasActiveConnection = connectionState &&
    (connectionState.state === 'connecting' || connectionState.state === 'connected');

  // Check for completed runs on mount / when flow changes
  useEffect(() => {
    let cancelled = false;

    const loadLatestCompletedRun = async () => {
      const batchSize = 50;
      let offset = 0;
      let latestSeenRunId: number | null = null;

      while (!cancelled) {
        const runs = await flowService.getFlowRuns(flow.id, batchSize, offset);
        if (latestSeenRunId === null) {
          latestSeenRunId = runs[0]?.id ?? null;
        }

        const completed = runs.find((run: FlowRunSummary) => run.status === 'COMPLETE');
        if (completed || runs.length < batchSize) {
          if (!cancelled) {
            setHasCompletedRuns(!!completed);
            setLatestRunId(completed?.id ?? latestSeenRunId);
          }
          return;
        }

        offset += batchSize;
      }
    };

    loadLatestCompletedRun().catch(() => {
      if (!cancelled) {
        setHasCompletedRuns(false);
        setLatestRunId(null);
      }
    });
    return () => { cancelled = true; };
  }, [flow.id]);

  const handleLoadFlow = async () => {
    await onLoadFlow(flow);
  };

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    setContextMenu({
      isOpen: true,
      position: { x: e.clientX, y: e.clientY }
    });
  };

  const handleMenuClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    
    // Get the button's position for the menu
    const rect = e.currentTarget.getBoundingClientRect();
    setContextMenu({
      isOpen: true,
      position: { x: rect.right - 160, y: rect.bottom } // Offset menu to the left of the button
    });
  };

  const closeContextMenu = () => {
    setContextMenu(prev => ({ ...prev, isOpen: false }));
  };

  const handleEdit = () => {
    setEditDialog(true);
  };

  const handleDuplicateFlow = async () => {
    try {
      await flowService.duplicateFlow(flow.id);
      onRefresh();
    } catch (error) {
      console.error('Failed to duplicate flow:', error);
    }
  };

  const handleDeleteFlow = async () => {
    if (window.confirm(`Are you sure you want to delete "${flow.name}"?`)) {
      try {
        await onDeleteFlow(flow);
      } catch (error) {
        console.error('Failed to delete flow:', error);
      }
    }
  };

  const handleRerun = async () => {
    if (!latestRunId) return;
    if (!window.confirm('Re-run using the parameters from the last completed run?')) return;

    try {
      // Load the flow first so the canvas shows the correct nodes/edges
      await onLoadFlow(flow);
      const sourceRun = await flowService.getFlowRun(flow.id, latestRunId);
      const rerunGraphNodes = resolveRerunGraphNodes(sourceRun.request_data, flow.nodes);
      const flowId = flow.id.toString();
      flowConnectionManager.setConnection(flowId, {
        state: 'connecting',
        startTime: Date.now(),
      });

      const abortController = await api.rerunFlowRun(flow.id, latestRunId, rerunGraphNodes, nodeContext, flowId);

      const currentConnection = flowConnectionManager.getConnection(flowId);
      if (currentConnection.state !== 'completed' && currentConnection.state !== 'error') {
        flowConnectionManager.setConnection(flowId, {
          state: 'connected',
          abortController,
        });
      }
    } catch (error) {
      console.error('Failed to rerun flow:', error);
      flowConnectionManager.setConnection(flow.id.toString(), {
        state: 'error',
        error: error instanceof Error ? error.message : 'Unknown error',
        abortController: null,
      });
      alert(`Rerun failed: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  };

  const formatDateTime = (dateString: string) => {
    return new Date(dateString).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      second: '2-digit',
      hour12: true
    });
  };

  // Filter out "default" tag
  const filteredTags = flow.tags?.filter(tag => tag !== 'default') || [];

  return (
    <>
      <div 
        className={cn(
          "group flex items-center justify-between px-4 py-3 transition-colors cursor-pointer",
          isActive 
            ? "border-l-2 border-blue-500" 
            : "hover-bg"
        )}
        onClick={handleLoadFlow}
        onContextMenu={handleContextMenu}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2 mb-1">
            <div className="flex items-center gap-1 min-w-0">
              {flow.is_template ? (
                <Layout size={14} className="text-blue-500 flex-shrink-0" />
              ) : (
                <FileText size={14} className={cn(
                  "flex-shrink-0",
                  isActive ? "text-blue-500" : "text-muted-foreground"
                )} />
              )}
              <span
                className={cn(
                  "text-subtitle font-medium text-left truncate",
                  isActive 
                    ? "text-blue-500" 
                    : "text-primary"
                )}
                title={flow.name}
              >
                {flow.name}
              </span>
            </div>
            
            {/* Active connection indicator - right aligned */}
            {hasActiveConnection && (
              <div className="flex items-center gap-1 flex-shrink-0">
                <Zap className="h-3 w-3 text-yellow-500 animate-pulse" />
                <span className="text-xs text-yellow-500 font-medium">Running</span>
              </div>
            )}
          </div>
          
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Calendar size={10} />
            <span>{formatDateTime(flow.created_at)}</span>
          </div>
          
          {filteredTags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1">
              {filteredTags.slice(0, 2).map(tag => (
                <Badge key={tag} variant="secondary" className="text-xs px-1 py-0">
                  {tag}
                </Badge>
              ))}
              {filteredTags.length > 2 && (
                <Badge variant="secondary" className="text-xs px-1 py-0">
                  +{filteredTags.length - 2}
                </Badge>
              )}
            </div>
          )}
        </div>
        
        <div className="flex items-center">
          <Button
            variant="ghost"
            size="icon"
            onClick={handleMenuClick}
            className="h-6 w-6 text-muted-foreground hover-item opacity-0 group-hover:opacity-100 transition-opacity rounded"
            title="More options"
          >
            <MoreHorizontal size={14} />
          </Button>
        </div>
      </div>

      <FlowContextMenu
        isOpen={contextMenu.isOpen}
        position={contextMenu.position}
        onClose={closeContextMenu}
        onEdit={handleEdit}
        onDuplicate={handleDuplicateFlow}
        onRerun={handleRerun}
        hasCompletedRuns={hasCompletedRuns}
        onDelete={handleDeleteFlow}
      />

      <FlowEditDialog
        flow={flow}
        isOpen={editDialog}
        onClose={() => setEditDialog(false)}
        onFlowUpdated={onRefresh}
      />
    </>
  );
} 