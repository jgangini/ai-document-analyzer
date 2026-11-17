import dagre from '@dagrejs/dagre';
import type {
  GraphEdgePath,
  GraphRenderNode,
  NodeRuntimeState,
  NodeRuntimeStatus,
} from './RAGChatPanel.types';

export type GraphNodeDefinition = { key: string; label: string; kind: string };
export type GraphEdgeDefinition = { source: string; target: string; condition?: string };
export type GraphDefinition = {
  nodes: GraphNodeDefinition[];
  edges: GraphEdgeDefinition[];
  start_node: string;
  end_node: string;
};
export const DEFAULT_GRAPH_DEFINITION: GraphDefinition = {
  nodes: [
    { key: 'classify_intent', label: 'Classify intent', kind: 'decision' },
    { key: 'search_response', label: 'Search response', kind: 'terminal_branch' },
    { key: 'resolve_scope', label: 'Resolve scope', kind: 'decision' },
    { key: 'classify_question', label: 'Classify question', kind: 'decision' },
    { key: 'resolve_facts', label: 'Resolve facts', kind: 'decision' },
    { key: 'decide_answerability', label: 'Decide answerability', kind: 'decision' },
    { key: 'retrieve_candidates', label: 'Retrieve candidates', kind: 'retrieval' },
    { key: 'fuse_page_evidence', label: 'Fuse page evidence', kind: 'merge' },
    { key: 'maybe_verify_visual', label: 'Maybe verify visual', kind: 'multimodal' },
    { key: 'synthesize_document_answer', label: 'Synthesize answer', kind: 'synthesis' },
    { key: 'persist_turn', label: 'Persist turn', kind: 'persistence' },
  ],
  edges: [
    { source: 'START', target: 'classify_intent', condition: '' },
    { source: 'classify_intent', target: 'search_response', condition: 'route=search' },
    { source: 'classify_intent', target: 'resolve_scope', condition: 'route=document' },
    { source: 'search_response', target: 'persist_turn', condition: '' },
    { source: 'resolve_scope', target: 'classify_question', condition: '' },
    { source: 'classify_question', target: 'resolve_facts', condition: '' },
    { source: 'resolve_facts', target: 'decide_answerability', condition: '' },
    { source: 'decide_answerability', target: 'retrieve_candidates', condition: 'answerability_route!=metadata' },
    { source: 'decide_answerability', target: 'synthesize_document_answer', condition: 'answerability_route=metadata' },
    { source: 'retrieve_candidates', target: 'fuse_page_evidence', condition: '' },
    { source: 'fuse_page_evidence', target: 'maybe_verify_visual', condition: '' },
    { source: 'maybe_verify_visual', target: 'synthesize_document_answer', condition: '' },
    { source: 'synthesize_document_answer', target: 'persist_turn', condition: '' },
    { source: 'persist_turn', target: 'END', condition: '' },
  ],
  start_node: 'classify_intent',
  end_node: 'persist_turn',
};

export const NODE_HEIGHT = 48;
export const NODE_WIDTH_MIN = 100;
export const NODE_WIDTH_MAX = 260;
export const CHAR_WIDTH_APPROX = 8;
export const NODE_PADDING_X = 24;

export function computeNodeWidth(label: string, key: string): number {
  const maxLen = Math.max(label.length, key.length);
  const contentWidth = maxLen * CHAR_WIDTH_APPROX;
  const total = NODE_PADDING_X * 2 + contentWidth;
  return Math.max(NODE_WIDTH_MIN, Math.min(NODE_WIDTH_MAX, total));
}

export function buildGraphWithDagre(
  baseNodes: GraphDefinition['nodes'],
  baseEdges: GraphDefinition['edges']
): { nodes: GraphRenderNode[]; edgePaths: GraphEdgePath[] } {
  const startNode = { key: 'START', label: 'START', kind: 'terminal' };
  const endNode = { key: 'END', label: 'END', kind: 'terminal' };
  const mergedNodes = [startNode, ...baseNodes, endNode];
  const nodeByKey = new Map<string, { key: string; label: string; kind: string }>();
  for (const node of mergedNodes) {
    nodeByKey.set(node.key, node);
  }
  const edges = baseEdges.filter((e) => nodeByKey.has(e.source) && nodeByKey.has(e.target));

  const g = new dagre.graphlib.Graph({ compound: false });
  g.setGraph({ rankdir: 'TB', nodesep: 60, ranksep: 80, marginx: 40, marginy: 40 });
  g.setDefaultEdgeLabel(() => ({ points: [] }));

  for (const node of mergedNodes) {
    const w = computeNodeWidth(node.label, node.key);
    g.setNode(node.key, { width: w, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target, {});
  }

  dagre.layout(g);

  const nodes: GraphRenderNode[] = [];
  for (const key of g.nodes()) {
    const n = g.node(key);
    const meta = nodeByKey.get(key);
    if (!n || !meta) continue;
    const w = (n as { width?: number }).width ?? computeNodeWidth(meta.label, meta.key);
    nodes.push({
      key: meta.key,
      label: meta.label,
      kind: meta.kind,
      level: (n as { rank?: number }).rank ?? 0,
      x: n.x,
      y: n.y,
      width: w,
    });
  }

  const edgePaths: GraphEdgePath[] = [];
  for (const edge of edges) {
    const e = g.edge(edge.source, edge.target);
    const points = e?.points as Array<{ x: number; y: number }> | undefined;
    if (points && points.length >= 2) {
      edgePaths.push({
        source: edge.source,
        target: edge.target,
        condition: edge.condition || '',
        points,
      });
    } else {
      const src = g.node(edge.source);
      const tgt = g.node(edge.target);
      if (src && tgt) {
        edgePaths.push({
          source: edge.source,
          target: edge.target,
          condition: edge.condition || '',
          points: [
            { x: src.x, y: src.y + NODE_HEIGHT / 2 },
            { x: tgt.x, y: tgt.y - NODE_HEIGHT / 2 },
          ],
        });
      }
    }
  }

  return { nodes, edgePaths };
}

export function resolveGraphRuntimeNodeStatus(
  nodeKey: string,
  graphRunStatus: 'idle' | 'running' | 'completed' | 'failed',
  graphNodeStates: Record<string, NodeRuntimeState>
): NodeRuntimeStatus {
  if (nodeKey === 'START') {
    if (graphRunStatus === 'running' || graphRunStatus === 'completed' || graphRunStatus === 'failed') {
      return 'completed';
    }
    return 'idle';
  }
  if (nodeKey === 'END') {
    if (graphRunStatus === 'completed') return 'completed';
    if (graphRunStatus === 'failed') return 'failed';
    if (graphRunStatus === 'running') return 'running';
    return 'idle';
  }
  return graphNodeStates[nodeKey]?.status || 'idle';
}

export function resolveGraphNodeClassName(status: NodeRuntimeStatus, selected?: boolean): string {
  if (selected) {
    if (status === 'running') return 'fill-blue-200 stroke-blue-600 text-blue-800';
    if (status === 'completed') return 'fill-emerald-200 stroke-emerald-600 text-emerald-800';
    if (status === 'failed') return 'fill-rose-200 stroke-rose-600 text-rose-800';
    return 'fill-gray-200 stroke-gray-500 text-oracle-dark-gray';
  }
  if (status === 'running') return 'fill-blue-50 stroke-blue-500 text-blue-700';
  if (status === 'completed') return 'fill-emerald-50 stroke-emerald-500 text-emerald-700';
  if (status === 'failed') return 'fill-rose-50 stroke-rose-500 text-rose-700';
  return 'fill-white stroke-gray-300 text-oracle-medium-gray';
}

export function resolveGraphEdgeClassName(
  edge: GraphDefinition['edges'][number],
  resolveNodeStatus: (nodeKey: string) => NodeRuntimeStatus
): string {
  const sourceStatus = resolveNodeStatus(edge.source);
  const targetStatus = resolveNodeStatus(edge.target);
  if (sourceStatus === 'failed' || targetStatus === 'failed') return 'stroke-rose-500';
  if (targetStatus === 'running') return 'stroke-blue-500';
  if (sourceStatus === 'completed' && targetStatus === 'completed') return 'stroke-emerald-500';
  if (sourceStatus === 'completed') return 'stroke-gray-400';
  return 'stroke-gray-300';
}

export function formatGraphNodeDuration(durationMs: number): string {
  if (durationMs < 1) return '<1ms';
  if (durationMs < 1000) return `${Math.max(1, Math.round(durationMs))}ms`;
  if (durationMs < 10_000) return `${(durationMs / 1000).toFixed(1)}s`;
  return `${Math.round(durationMs / 1000)}s`;
}
