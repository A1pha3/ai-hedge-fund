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
  setCurrentFlowId,
  setNodeInternalState,
} from '@/hooks/use-node-state';

function CreateFlowButton() {
  const { createNewFlow } = useFlowContext();

  return <button onClick={() => void createNewFlow()}>Create new flow</button>;
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
