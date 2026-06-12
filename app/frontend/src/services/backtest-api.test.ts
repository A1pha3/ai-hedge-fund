import { afterEach, describe, expect, it, vi } from 'vitest';

import { backtestApi } from './backtest-api';

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

describe('backtestApi.runBacktest', () => {
  it('consumes multi-line SSE payloads for backtest progress and completion', async () => {
    mockFetch(
      sseResponse([
        'event: start\ndata: {"agent":"backtest","status":"Starting"}\n\n',
        [
          'event: progress',
          'data: {"agent":"backtest",',
          'data: "status":"Day 1",',
          'data: "analysis":"{\\"date\\": \\"2026-01-02\\", \\"portfolio_value\\": 101000}"}',
        ].join('\n') + '\n\n',
        [
          'event: complete',
          'data: {"data":{"performance_metrics":{"sharpe_ratio":1.2},',
          'data: "final_portfolio":{"cash":1000,"margin_used":0,"positions":{}},',
          'data: "total_days":10}}',
        ].join('\n') + '\n\n',
      ]),
    );

    const nodeContext = {
      resetAllNodes: vi.fn(),
      updateAgentNode: vi.fn(),
      updateAgentNodes: vi.fn(),
      setOutputNodeData: vi.fn(),
    };

    backtestApi.runBacktest(
      {
        tickers: ['AAPL'],
        graph_nodes: [{ id: 'backtest_alpha123' }],
        graph_edges: [],
        start_date: '2026-01-01',
        end_date: '2026-01-10',
      },
      nodeContext as never,
      'flow-2',
    );

    await vi.waitFor(() => {
      expect(nodeContext.updateAgentNode).toHaveBeenCalledWith(
        'flow-2',
        'backtest',
        expect.objectContaining({
          status: 'IN_PROGRESS',
          message: 'Day 1',
          backtestResults: [{ date: '2026-01-02', portfolio_value: 101000 }],
        }),
      );
    });

    await vi.waitFor(() => {
      expect(nodeContext.setOutputNodeData).toHaveBeenCalledWith(
        'flow-2',
        expect.objectContaining({
          performance_metrics: { sharpe_ratio: 1.2 },
          total_days: 10,
        }),
      );
    });
  });
});
