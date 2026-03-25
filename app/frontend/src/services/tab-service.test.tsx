import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/components/settings/settings', () => ({
  Settings: () => <div>Settings Content</div>,
}));

vi.mock('@/components/tabs/flow-tab-content', () => ({
  FlowTabContent: ({ flow }: { flow: { name: string } }) => <div>Flow Content {flow.name}</div>,
}));

vi.mock('@/components/workspaces/replay-artifacts-workspace', () => ({
  ReplayArtifactsWorkspace: () => <div>Replay Workspace Content</div>,
}));

import { TabService } from '@/services/tab-service';

describe('TabService replay-artifacts support', () => {
  it('creates a replay-artifacts tab with workspace content', () => {
    const tab = TabService.createReplayArtifactsTab();

    expect(tab.type).toBe('replay-artifacts');
    expect(tab.title).toBe('Replay Artifacts');

    render(<>{tab.content}</>);
    expect(screen.getByText('Replay Workspace Content')).toBeInTheDocument();
  });

  it('restores a persisted replay-artifacts tab', () => {
    const restored = TabService.restoreTab({
      type: 'replay-artifacts',
      title: 'Replay Artifacts',
    });

    expect(restored.type).toBe('replay-artifacts');
    expect(restored.title).toBe('Replay Artifacts');

    render(<>{restored.content}</>);
    expect(screen.getByText('Replay Workspace Content')).toBeInTheDocument();
  });
});