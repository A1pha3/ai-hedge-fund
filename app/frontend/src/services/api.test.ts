import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from './api';

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });

  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  });
}

function mockFetch(response: Response) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('api.runHedgeFund', () => {
  it('consumes multi-line SSE progress payloads and updates the mapped agent node', async () => {
    mockFetch(
      sseResponse([
        'event: start\ndata: {"message":"boot"}\n\n',
        [
          'event: progress',
          'data: {"agent":"technical_agent",',
          'data: "status":"Done",',
          'data: "ticker":"AAPL",',
          'data: "analysis":"ok",',
          'data: "timestamp":"2026-06-12T09:30:00"}',
        ].join('\n') + '\n\n',
      ]),
    );

    const nodeContext = {
      resetAllNodes: vi.fn(),
      updateAgentNode: vi.fn(),
      updateAgentNodes: vi.fn(),
      setOutputNodeData: vi.fn(),
    };

    api.runHedgeFund(
      {
        tickers: ['AAPL'],
        graph_nodes: [{ id: 'technical_abc123' }],
        graph_edges: [],
      },
      nodeContext as never,
      'flow-1',
    );

    await vi.waitFor(() => {
      expect(nodeContext.updateAgentNode).toHaveBeenCalledWith(
        'flow-1',
        'technical_abc123',
        expect.objectContaining({
          status: 'COMPLETE',
          ticker: 'AAPL',
          message: 'Done',
          analysis: 'ok',
          timestamp: '2026-06-12T09:30:00',
        }),
      );
    });
  });
});
