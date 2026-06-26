import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import {
  clearAllNodeStates,
  clearFlowNodeStates,
  getAllNodeStates,
  getCurrentFlowId,
  getNodeInternalState,
  setCurrentFlowId,
  setNodeInternalState,
  useNodeState,
} from './use-node-state';

describe('FlowStateManager flow isolation (NS-20)', () => {
  beforeEach(() => {
    setCurrentFlowId(null);
    clearAllNodeStates();
    clearFlowNodeStates('flow-a');
    clearFlowNodeStates('flow-b');
  });

  it('isolates node state by flow id (flow-a state invisible from flow-b)', () => {
    setCurrentFlowId('flow-a');
    setNodeInternalState('node-1', { ticker: 'AAPL' });

    setCurrentFlowId('flow-b');
    setNodeInternalState('node-1', { ticker: 'MSFT' });

    expect(getNodeInternalState('node-1')).toEqual({ ticker: 'MSFT' });

    setCurrentFlowId('flow-a');
    expect(getNodeInternalState('node-1')).toEqual({ ticker: 'AAPL' });
  });

  it('getAllNodeStates returns only current-flow states (strips flow prefix)', () => {
    setCurrentFlowId('flow-a');
    setNodeInternalState('node-a', { ticker: 'AAPL' });

    setCurrentFlowId('flow-b');
    setNodeInternalState('node-b', { ticker: 'MSFT' });

    const states = Object.fromEntries(getAllNodeStates());
    expect(states).toHaveProperty('node-b');
    expect(states).not.toHaveProperty('node-a');
    expect(states).not.toHaveProperty('flow-a:node-a');
  });

  it('clearAllNodeStates clears only current flow, preserves other flows', () => {
    setCurrentFlowId('flow-a');
    setNodeInternalState('node-a', { ticker: 'AAPL' });

    setCurrentFlowId('flow-b');
    setNodeInternalState('node-b', { ticker: 'MSFT' });

    clearAllNodeStates();

    setCurrentFlowId('flow-a');
    expect(getNodeInternalState('node-a')).toEqual({ ticker: 'AAPL' });
  });

  it('clearFlowNodeStates clears only the named flow', () => {
    setCurrentFlowId('flow-a');
    setNodeInternalState('node-a', { ticker: 'AAPL' });
    setCurrentFlowId('flow-b');
    setNodeInternalState('node-b', { ticker: 'MSFT' });

    clearFlowNodeStates('flow-a');

    setCurrentFlowId('flow-a');
    expect(getNodeInternalState('node-a')).toBeUndefined();
    setCurrentFlowId('flow-b');
    expect(getNodeInternalState('node-b')).toEqual({ ticker: 'MSFT' });
  });
});

describe('useNodeState hook (NS-20)', () => {
  beforeEach(() => {
    setCurrentFlowId(null);
    clearAllNodeStates();
    clearFlowNodeStates('flow-h');
  });

  it('reads initial value and persists updates to flow state manager', () => {
    setCurrentFlowId('flow-h');

    const { result } = renderHook(() => useNodeState<string>('node-h', 'ticker', 'DEFAULT'));

    expect(result.current[0]).toBe('DEFAULT');

    act(() => {
      result.current[1]('AAPL');
    });
    expect(result.current[0]).toBe('AAPL');

    expect(getNodeInternalState('node-h')).toEqual({ ticker: 'AAPL' });
  });

  it('getCurrentFlowId reflects setCurrentFlowId', () => {
    setCurrentFlowId('flow-h');
    expect(getCurrentFlowId()).toBe('flow-h');
    setCurrentFlowId(null);
    expect(getCurrentFlowId()).toBeNull();
  });
});
