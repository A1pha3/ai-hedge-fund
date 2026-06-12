export interface ParsedSseEvent {
  event: string;
  data: unknown;
}

const SSE_EVENT_BOUNDARY = /\r?\n\r?\n/;
const SSE_LINE_BOUNDARY = /\r?\n/;

export function extractCompleteSseEvents(buffer: string): { events: string[]; remainder: string } {
  const parts = buffer.split(SSE_EVENT_BOUNDARY);
  const remainder = parts.pop() ?? '';
  return {
    events: parts.filter((part) => part.trim().length > 0),
    remainder,
  };
}

export function parseSseEvent(eventText: string): ParsedSseEvent | null {
  let eventName = '';
  const dataLines: string[] = [];

  for (const line of eventText.split(SSE_LINE_BOUNDARY)) {
    if (line.startsWith('event:')) {
      eventName = line.slice('event:'.length).trim();
      continue;
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trimStart());
    }
  }

  if (!eventName || dataLines.length === 0) {
    return null;
  }

  return {
    event: eventName,
    data: JSON.parse(dataLines.join('\n')),
  };
}

export function asSseRecord(data: unknown): Record<string, unknown> | null {
  return data && typeof data === 'object' ? (data as Record<string, unknown>) : null;
}
