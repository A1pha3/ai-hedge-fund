import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const authFetchMock = vi.fn();

vi.mock('@/services/auth-api', () => ({
  authFetch: (...args: unknown[]) => authFetchMock(...args),
}));

import { flowService } from './flow-service';

function jsonRes(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

const FLOW = {
  id: 7,
  name: 'Momentum Flow',
  description: 'Sample flow',
  nodes: [],
  edges: [],
  viewport: { x: 0, y: 0, zoom: 1 },
  data: {},
  is_template: false,
  tags: [],
  created_at: '2026-06-12T00:00:00',
  updated_at: '2026-06-12T00:00:00',
};

describe('flowService', () => {
  beforeEach(() => {
    authFetchMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('POSTs createFlow with the serialized flow payload', async () => {
    authFetchMock.mockResolvedValue(jsonRes(FLOW));

    const result = await flowService.createFlow({
      name: 'Momentum Flow',
      description: 'Sample flow',
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      data: { draft: true },
    });

    expect(result.id).toBe(7);
    const [url, init] = authFetchMock.mock.calls[0];
    expect(url).toContain('/flows/');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({
      name: 'Momentum Flow',
      description: 'Sample flow',
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      data: { draft: true },
    });
  });

  it('encodes duplicateFlow newName into the query string', async () => {
    authFetchMock.mockResolvedValue(jsonRes(FLOW));

    await flowService.duplicateFlow(7, 'Copy / Alpha');

    const [url, init] = authFetchMock.mock.calls[0];
    expect(url).toContain('/flows/7/duplicate');
    expect(url).toContain('new_name=Copy%20%2F%20Alpha');
    expect(init.method).toBe('POST');
  });

  it('createDefaultFlow delegates the default name and description', async () => {
    authFetchMock.mockResolvedValue(jsonRes(FLOW));

    await flowService.createDefaultFlow([], [], { x: 1, y: 2, zoom: 3 });

    const [, init] = authFetchMock.mock.calls[0];
    expect(JSON.parse(String(init.body))).toMatchObject({
      name: 'My First Flow',
      description: 'Welcome to AI Hedge Fund! Start building your flow here.',
      viewport: { x: 1, y: 2, zoom: 3 },
    });
  });

  it('includes limit and offset when fetching flow runs', async () => {
    authFetchMock.mockResolvedValue(jsonRes([]));

    await flowService.getFlowRuns(12, 25, 50);

    const [url] = authFetchMock.mock.calls[0];
    expect(url).toContain('/flows/12/runs/?limit=25&offset=50');
  });

  it('throws on non-2xx createFlow responses', async () => {
    authFetchMock.mockResolvedValue(new Response('bad', { status: 500 }));

    await expect(
      flowService.createFlow({
        name: 'Broken flow',
        nodes: [],
        edges: [],
      }),
    ).rejects.toThrow('Failed to create flow');
  });
});
