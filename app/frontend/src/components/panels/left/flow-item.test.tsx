import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// --- Mocks ---

const { getFlowRunsMock, rerunFlowRunMock } = vi.hoisted(() => ({
  getFlowRunsMock: vi.fn(),
  rerunFlowRunMock: vi.fn(),
}));

vi.mock('@/services/flow-service', () => ({
  flowService: {
    getFlowRuns: getFlowRunsMock,
    rerunFlowRun: rerunFlowRunMock,
    duplicateFlow: vi.fn(),
  },
}));

vi.mock('@/hooks/use-flow-connection', () => ({
  useFlowConnectionState: () => ({ state: 'idle' }),
  flowConnectionManager: {
    getConnection: vi.fn(() => ({ state: 'idle' })),
    setConnection: vi.fn(),
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
    rerunFlowRunMock.mockReset();
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
      expect(getFlowRunsMock).toHaveBeenCalledWith(42, 5);
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
      expect(getFlowRunsMock).toHaveBeenCalledWith(42, 5);
    });

    const moreButton = container.querySelector('[title="More options"]');
    await userEvent.setup().click(moreButton!);

    await waitFor(() => {
      expect(screen.getByText('Edit')).toBeInTheDocument();
    });

    expect(screen.queryByText('Rerun Last')).not.toBeInTheDocument();
  });
});
