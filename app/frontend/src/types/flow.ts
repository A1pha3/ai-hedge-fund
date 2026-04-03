import type { Edge, Node, Viewport } from '@xyflow/react';

export type FlowNode = Node<Record<string, unknown>>;
export type FlowEdge = Edge;
export type FlowViewport = Viewport;
export type FlowData = Record<string, unknown>;

export interface Flow {
  id: number;
  name: string;
  description?: string;
  nodes: FlowNode[];
  edges: FlowEdge[];
  viewport?: FlowViewport;
  data?: FlowData;
  is_template: boolean;
  tags?: string[];
  created_at: string;
  updated_at?: string;
}
