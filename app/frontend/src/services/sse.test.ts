import { describe, expect, it } from 'vitest';

import { extractCompleteSseEvents, parseSseEvent } from './sse';

describe('SSE helpers', () => {
  it('parses multi-line data fields into a single JSON payload', () => {
    const parsed = parseSseEvent(
      [
        'event: progress',
        'data: {"agent":"backtest",',
        'data: "status":"Done",',
        'data: "analysis":"ok"}',
      ].join('\n'),
    );

    expect(parsed).toEqual({
      event: 'progress',
      data: {
        agent: 'backtest',
        status: 'Done',
        analysis: 'ok',
      },
    });
  });

  it('extracts complete events and preserves an incomplete trailing buffer', () => {
    const source = [
      'event: start',
      'data: {"step":1}',
      '',
      'event: progress',
      'data: {"step":2',
    ].join('\n');

    const result = extractCompleteSseEvents(source);

    expect(result.events).toEqual([
      ['event: start', 'data: {"step":1}'].join('\n'),
    ]);
    expect(result.remainder).toBe(['event: progress', 'data: {"step":2'].join('\n'));
  });
});
