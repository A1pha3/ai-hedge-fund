import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const reactFlowInstance = {
  getNodes: vi.fn(() => []),
  getEdges: vi.fn(() => []),
  getViewport: vi.fn(() => ({ x: 0, y: 0, zoom: 1 })),
  setNodes: vi.fn(),
  setEdges: vi.fn(),
  setViewport: vi.fn(),
  fitView: vi.fn(),
};

vi.mock('@xyflow/react', () => ({
  MarkerType: { ArrowClosed: 'arrowclosed' },
  useReactFlow: () => reactFlowInstance,
}));

const { createFlowMock, updateFlowMock } = vi.hoisted(() => ({
  createFlowMock: vi.fn(async (payload: unknown) => ({
    id: 99,
    name: 'Draft Flow',
    description: null,
    nodes: [],
    edges: [],
    viewport: { x: 0, y: 0, zoom: 1 },
    data: (payload as { data?: unknown })?.data ?? {},
  })),
  updateFlowMock: vi.fn(),
}));

vi.mock('@/services/flow-service', () => ({
  flowService: {
    createFlow: createFlowMock,
    updateFlow: updateFlowMock,
  },
}));

import { FlowProvider, useFlowContext } from './flow-context';
import {
  clearAllNodeStates,
  clearFlowNodeStates,
  getAllNodeStates,
  getCurrentFlowId,
  getNodeInternalState,
  setCurrentFlowId,
  setNodeInternalState,
} from '@/hooks/use-node-state';

interface MockFlow {
  id: number;
  name: string;
  description?: string | null;
  nodes: unknown[];
  edges: unknown[];
  viewport?: { x: number; y: number; zoom: number } | null;
  data?: { nodeStates?: Record<string, unknown> } | null;
}

function CreateFlowButton() {
  const { createNewFlow } = useFlowContext();

  return <button onClick={() => void createNewFlow()}>Create new flow</button>;
}

function LoadFlowButton({ flow }: { flow: MockFlow }) {
  const { loadFlow } = useFlowContext();

  return <button onClick={() => void loadFlow(flow as never)}>Load flow</button>;
}

function SaveFlowButton() {
  const { saveCurrentFlow } = useFlowContext();

  return <button onClick={() => void saveCurrentFlow()}>Save flow</button>;
}

describe('FlowProvider createNewFlow', () => {
  beforeEach(() => {
    reactFlowInstance.setNodes.mockClear();
    reactFlowInstance.setEdges.mockClear();
    reactFlowInstance.setViewport.mockClear();
    createFlowMock.mockClear();
    setCurrentFlowId(null);
    clearAllNodeStates();
    clearFlowNodeStates('flow-a');
    clearFlowNodeStates('flow-b');
  });

  it('clears only the current flow state and preserves other saved flows', async () => {
    setCurrentFlowId('flow-a');
    setNodeInternalState('node-a', { ticker: 'AAPL' });

    setCurrentFlowId('flow-b');
    setNodeInternalState('node-b', { ticker: 'MSFT' });

    setCurrentFlowId('flow-a');

    render(
      <FlowProvider>
        <CreateFlowButton />
      </FlowProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Create new flow' }));

    await waitFor(() => {
      expect(reactFlowInstance.setNodes).toHaveBeenCalledWith([]);
    });

    const persistedStates = Object.fromEntries(getAllNodeStates());

    expect(persistedStates).not.toHaveProperty('flow-a:node-a');
    expect(persistedStates).toHaveProperty('flow-b:node-b');
  });

  it('does not persist other flows state when saving a new unsaved draft', async () => {
    setCurrentFlowId('flow-a');
    setNodeInternalState('node-a', { ticker: 'AAPL' });

    setCurrentFlowId('flow-b');
    setNodeInternalState('node-b', { ticker: 'MSFT' });

    render(
      <FlowProvider>
        <CreateFlowButton />
        <SaveFlowButton />
      </FlowProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Create new flow' }));

    await waitFor(() => {
      expect(reactFlowInstance.setNodes).toHaveBeenCalledWith([]);
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save flow' }));

    await waitFor(() => {
      expect(createFlowMock).toHaveBeenCalled();
    });

    const payload = createFlowMock.mock.calls[0][0] as { data: { nodeStates: Record<string, unknown> } };
    expect(payload.data.nodeStates).not.toHaveProperty('flow-a:node-a');
    expect(payload.data.nodeStates).not.toHaveProperty('flow-b:node-b');
  });
});

// NS-20: loadFlow 防回归测试 — CLAUDE.md 反模式 "加载 flow 不清 config state"
// (flow-context.tsx loadFlow 注释: "DO NOT clear configuration state when loading flows")
describe('FlowProvider loadFlow', () => {
  beforeEach(() => {
    reactFlowInstance.setNodes.mockClear();
    reactFlowInstance.setEdges.mockClear();
    reactFlowInstance.setViewport.mockClear();
    setCurrentFlowId(null);
    clearAllNodeStates();
    clearFlowNodeStates('flow-a');
    clearFlowNodeStates('2');
  });

  it('does NOT clear other flows configuration state when loading (CLAUDE.md anti-pattern guard)', async () => {
    // 预置: flow-a 有 config state
    setCurrentFlowId('flow-a');
    setNodeInternalState('node-a', { ticker: 'AAPL' });

    // 加载 flow 2 (id=2) — 不应清掉 flow-a 的 state
    const flow2: MockFlow = {
      id: 2,
      name: 'Flow B',
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      data: { nodeStates: {} },
    };

    render(
      <FlowProvider>
        <LoadFlowButton flow={flow2} />
      </FlowProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Load flow' }));

    await waitFor(() => {
      expect(reactFlowInstance.setNodes).toHaveBeenCalledWith([]);
    });

    // 反模式守卫: loadFlow 后切回 flow-a, 其 config state 仍在 (CLAUDE.md "不清 config state")
    // (getAllNodeStates 在 currentFlowId set 时只返回 current flow, 故切回 flow-a 验证)
    setCurrentFlowId('flow-a');
    expect(getNodeInternalState('node-a')).toEqual({ ticker: 'AAPL' });
  });

  it('restores flow.data.nodeStates into internal state and sets current flow id', async () => {
    const flow2: MockFlow = {
      id: 2,
      name: 'Flow B',
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      data: { nodeStates: { 'node-x': { ticker: 'MSFT' } } },
    };

    render(
      <FlowProvider>
        <LoadFlowButton flow={flow2} />
      </FlowProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Load flow' }));

    await waitFor(() => {
      expect(getCurrentFlowId()).toBe('2');
    });

    // restored nodeState 可经 getNodeInternalState 取到
    expect(getNodeInternalState('node-x')).toEqual({ ticker: 'MSFT' });
  });
});
