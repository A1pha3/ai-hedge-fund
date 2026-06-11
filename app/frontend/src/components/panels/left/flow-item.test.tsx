import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// --- Mocks ---

const { getFlowRunsMock, getFlowRunMock, rerunStreamMock, setConnectionMock, getConnectionMock } = vi.hoisted(() => ({
  getFlowRunsMock: vi.fn(),
  getFlowRunMock: vi.fn(),
  rerunStreamMock: vi.fn(),
  setConnectionMock: vi.fn(),
  getConnectionMock: vi.fn(() => ({ state: 'idle' })),
}));

vi.mock('@/services/flow-service', () => ({
  flowService: {
    getFlowRuns: getFlowRunsMock,
    getFlowRun: getFlowRunMock,
    duplicateFlow: vi.fn(),
  },
}));

vi.mock('@/services/api', () => ({
  api: {
    rerunFlowRun: rerunStreamMock,
  },
}));

vi.mock('@/contexts/node-context', () => ({
  useNodeContext: () => ({
    resetAllNodes: vi.fn(),
    updateAgentNodes: vi.fn(),
    updateAgentNode: vi.fn(),
    setOutputNodeData: vi.fn(),
  }),
}));

vi.mock('@/hooks/use-flow-connection', () => ({
  useFlowConnectionState: () => ({ state: 'idle' }),
  flowConnectionManager: {
    getConnection: getConnectionMock,
    setConnection: setConnectionMock,
  },
}));

// Mock @xyflow/react
vi.mock('@xyflow/react', () => ({
  useReactFlow: () => ({
    getNodes: vi.fn(() => []),
    getEdges: vi.fn(() => []),
    setNodes: vi.fn(),
    setEdges: vi.fn(),
    setViewport: vi.fn(),
    getViewport: vi.fn(() => ({ x: 0, y: 0, zoom: 1 })),
  }),
}));

// Mock FlowEditDialog (requires TabsProvider context)
vi.mock('@/components/panels/left/flow-edit-dialog', () => ({
  FlowEditDialog: () => null,
}));

// Mock sonner toast
vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

// --- Import components under test ---

import { FlowContextMenu } from '@/components/panels/left/flow-context-menu';
import FlowItem from '@/components/panels/left/flow-item';
import type { Flow } from '@/types/flow';

// --- Test fixtures ---

const baseFlow: Flow = {
  id: 42,
  name: 'Test Flow',
  description: 'A test flow',
  nodes: [],
  edges: [],
  is_template: false,
  created_at: '2026-06-01T10:00:00Z',
};

// --- Tests ---

describe('FlowContextMenu rerun button', () => {
  it('does not render rerun button when hasCompletedRuns is false', () => {
    render(
      <FlowContextMenu
        isOpen={true}
        position={{ x: 0, y: 0 }}
        onClose={vi.fn()}
        onEdit={vi.fn()}
        onDuplicate={vi.fn()}
        onDelete={vi.fn()}
        onRerun={vi.fn()}
        hasCompletedRuns={false}
      />,
    );

    expect(screen.queryByText('Rerun Last')).not.toBeInTheDocument();
    expect(screen.getByText('Edit')).toBeInTheDocument();
    expect(screen.getByText('Duplicate')).toBeInTheDocument();
  });

  it('renders rerun button when hasCompletedRuns is true and onRerun is provided', () => {
    render(
      <FlowContextMenu
        isOpen={true}
        position={{ x: 0, y: 0 }}
        onClose={vi.fn()}
        onEdit={vi.fn()}
        onDuplicate={vi.fn()}
        onDelete={vi.fn()}
        onRerun={vi.fn()}
        hasCompletedRuns={true}
      />,
    );

    expect(screen.getByText('Rerun Last')).toBeInTheDocument();
  });

  it('does not render rerun button when onRerun is undefined even if hasCompletedRuns is true', () => {
    render(
      <FlowContextMenu
        isOpen={true}
        position={{ x: 0, y: 0 }}
        onClose={vi.fn()}
        onEdit={vi.fn()}
        onDuplicate={vi.fn()}
        onDelete={vi.fn()}
        hasCompletedRuns={true}
      />,
    );

    expect(screen.queryByText('Rerun Last')).not.toBeInTheDocument();
  });
});

describe('FlowItem rerun integration', () => {
  const mockOnLoadFlow = vi.fn().mockResolvedValue(undefined);
  const mockOnDeleteFlow = vi.fn().mockResolvedValue(undefined);
  const mockOnRefresh = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    vi.clearAllMocks();
    getFlowRunsMock.mockReset();
    getFlowRunMock.mockReset();
    rerunStreamMock.mockReset();
    setConnectionMock.mockReset();
    getConnectionMock.mockReset();
    getConnectionMock.mockReturnValue({ state: 'idle' });
    getFlowRunMock.mockResolvedValue({
      request_data: {
        graph_nodes: baseFlow.nodes,
      },
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
  });

  it('shows rerun button in context menu when flow has a completed run', async () => {
    getFlowRunsMock.mockResolvedValue([
      { id: 10, flow_id: 42, status: 'COMPLETE', run_number: 1, created_at: '2026-06-01T12:00:00Z' },
    ]);

    const { container } = render(
      <FlowItem
        flow={baseFlow}
        onLoadFlow={mockOnLoadFlow}
        onDeleteFlow={mockOnDeleteFlow}
        onRefresh={mockOnRefresh}
        isActive={true}
      />,
    );

    // Wait for the flow runs to be fetched
    await waitFor(() => {
      expect(getFlowRunsMock).toHaveBeenCalledWith(42, 50, 0);
    });

    // Open the context menu by clicking the more button
    const moreButton = container.querySelector('[title="More options"]');
    expect(moreButton).toBeTruthy();
    await userEvent.setup().click(moreButton!);

    await waitFor(() => {
      expect(screen.getByText('Rerun Last')).toBeInTheDocument();
    });
  });

  it('does not show rerun button when all runs are non-complete', async () => {
    getFlowRunsMock.mockResolvedValue([
      { id: 10, flow_id: 42, status: 'ERROR', run_number: 1, created_at: '2026-06-01T12:00:00Z' },
    ]);

    const { container } = render(
      <FlowItem
        flow={baseFlow}
        onLoadFlow={mockOnLoadFlow}
        onDeleteFlow={mockOnDeleteFlow}
        onRefresh={mockOnRefresh}
        isActive={true}
      />,
    );

    await waitFor(() => {
      expect(getFlowRunsMock).toHaveBeenCalledWith(42, 50, 0);
    });

    const moreButton = container.querySelector('[title="More options"]');
    await userEvent.setup().click(moreButton!);

    await waitFor(() => {
      expect(screen.getByText('Edit')).toBeInTheDocument();
    });

    expect(screen.queryByText('Rerun Last')).not.toBeInTheDocument();
  });

  it('keeps searching run history until it finds the latest completed run', async () => {
    getFlowRunsMock
      .mockResolvedValueOnce(
        Array.from({ length: 50 }, (_, index) => ({
          id: 60 - index,
          flow_id: 42,
          status: index % 2 === 0 ? 'ERROR' : 'CANCELLED',
          run_number: 60 - index,
          created_at: `2026-06-${String((index % 28) + 1).padStart(2, '0')}T12:00:00Z`,
        })),
      )
      .mockResolvedValueOnce([
        { id: 10, flow_id: 42, status: 'COMPLETE', run_number: 10, created_at: '2026-06-01T12:00:00Z' },
      ]);

    const { container } = render(
      <FlowItem
        flow={baseFlow}
        onLoadFlow={mockOnLoadFlow}
        onDeleteFlow={mockOnDeleteFlow}
        onRefresh={mockOnRefresh}
        isActive={true}
      />,
    );

    await waitFor(() => {
      expect(getFlowRunsMock).toHaveBeenNthCalledWith(1, 42, 50, 0);
      expect(getFlowRunsMock).toHaveBeenNthCalledWith(2, 42, 50, 50);
    });

    const moreButton = container.querySelector('[title="More options"]');
    expect(moreButton).toBeTruthy();
    await userEvent.setup().click(moreButton!);

    await waitFor(() => {
      expect(screen.getByText('Rerun Last')).toBeInTheDocument();
    });
  });

  it('rerun last uses the SSE rerun helper and updates connection state', async () => {
    getFlowRunsMock.mockResolvedValue([
      { id: 10, flow_id: 42, status: 'COMPLETE', run_number: 1, created_at: '2026-06-01T12:00:00Z' },
    ]);
    rerunStreamMock.mockResolvedValue(vi.fn());

    const { container } = render(
      <FlowItem
        flow={baseFlow}
        onLoadFlow={mockOnLoadFlow}
        onDeleteFlow={mockOnDeleteFlow}
        onRefresh={mockOnRefresh}
        isActive={true}
      />,
    );

    await waitFor(() => {
      expect(getFlowRunsMock).toHaveBeenCalledWith(42, 50, 0);
    });

    const moreButton = container.querySelector('[title="More options"]');
    expect(moreButton).toBeTruthy();
    await userEvent.setup().click(moreButton!);

    await waitFor(() => {
      expect(screen.getByText('Rerun Last')).toBeInTheDocument();
    });

    await userEvent.setup().click(screen.getByText('Rerun Last'));

    await waitFor(() => {
      expect(mockOnLoadFlow).toHaveBeenCalledWith(baseFlow);
      expect(getFlowRunMock).toHaveBeenCalledWith(42, 10);
      expect(rerunStreamMock).toHaveBeenCalledWith(42, 10, baseFlow.nodes, expect.any(Object), '42');
    });

    expect(setConnectionMock).toHaveBeenNthCalledWith(
      1,
      '42',
      expect.objectContaining({ state: 'connecting' }),
    );
    expect(setConnectionMock).toHaveBeenNthCalledWith(
      2,
      '42',
      expect.objectContaining({ state: 'connected', abortController: expect.any(Function) }),
    );
  });

  it('rerun last uses the historical run graph for SSE node mapping', async () => {
    getFlowRunsMock.mockResolvedValue([
      { id: 10, flow_id: 42, status: 'COMPLETE', run_number: 1, created_at: '2026-06-01T12:00:00Z' },
    ]);
    getFlowRunMock.mockResolvedValue({
      request_data: {
        graph_nodes: [{ id: 'historical-node' }],
      },
    });
    rerunStreamMock.mockResolvedValue(vi.fn());

    const { container } = render(
      <FlowItem
        flow={{ ...baseFlow, nodes: [{ id: 'live-node' }] as Flow['nodes'] }}
        onLoadFlow={mockOnLoadFlow}
        onDeleteFlow={mockOnDeleteFlow}
        onRefresh={mockOnRefresh}
        isActive={true}
      />,
    );

    await waitFor(() => {
      expect(getFlowRunsMock).toHaveBeenCalledWith(42, 50, 0);
    });

    const moreButton = container.querySelector('[title="More options"]');
    expect(moreButton).toBeTruthy();
    await userEvent.setup().click(moreButton!);
    await waitFor(() => {
      expect(screen.getByText('Rerun Last')).toBeInTheDocument();
    });

    await userEvent.setup().click(screen.getByText('Rerun Last'));

    await waitFor(() => {
      expect(rerunStreamMock).toHaveBeenCalledWith(42, 10, [{ id: 'historical-node' }], expect.any(Object), '42');
    });
  });

  it('does not overwrite a completed rerun connection back to connected', async () => {
    getFlowRunsMock.mockResolvedValue([
      { id: 10, flow_id: 42, status: 'COMPLETE', run_number: 1, created_at: '2026-06-01T12:00:00Z' },
    ]);
    rerunStreamMock.mockResolvedValue(vi.fn());
    getConnectionMock.mockReturnValue({ state: 'completed' });

    const { container } = render(
      <FlowItem
        flow={baseFlow}
        onLoadFlow={mockOnLoadFlow}
        onDeleteFlow={mockOnDeleteFlow}
        onRefresh={mockOnRefresh}
        isActive={true}
      />,
    );

    await waitFor(() => {
      expect(getFlowRunsMock).toHaveBeenCalledWith(42, 50, 0);
    });

    const moreButton = container.querySelector('[title="More options"]');
    expect(moreButton).toBeTruthy();
    await userEvent.setup().click(moreButton!);
    await waitFor(() => {
      expect(screen.getByText('Rerun Last')).toBeInTheDocument();
    });

    await userEvent.setup().click(screen.getByText('Rerun Last'));

    await waitFor(() => {
      expect(getConnectionMock).toHaveBeenCalledWith('42');
    });
    expect(setConnectionMock).not.toHaveBeenCalledWith(
      '42',
      expect.objectContaining({ state: 'connected' }),
    );
  });
});
