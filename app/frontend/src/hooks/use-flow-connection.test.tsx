import { render } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { flowConnectionManager, useFlowConnectionState } from './use-flow-connection';

function ListenerProbe({ flowId }: { flowId: string }) {
  useFlowConnectionState(flowId);
  return null;
}

function getListenerSet(): Set<() => void> {
  return (flowConnectionManager as unknown as { listeners: Set<() => void> }).listeners;
}

describe('useFlowConnectionState', () => {
  beforeEach(() => {
    getListenerSet().clear();
  });

  it('removes its connection listener when the consumer unmounts', () => {
    const { unmount } = render(<ListenerProbe flowId="flow-1" />);

    expect(getListenerSet().size).toBe(1);

    unmount();

    expect(getListenerSet().size).toBe(0);
  });
});
