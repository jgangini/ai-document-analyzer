import type { KeyboardEvent, MouseEvent, RefObject } from 'react';

import { NODE_HEIGHT, type GraphDefinition } from './RAGChatPanel.graph';
import type {
  GraphEdgePath,
  GraphRenderNode,
  NodeRuntimeState,
  NodeRuntimeStatus,
} from './RAGChatPanel.types';

type GraphCanvasSize = { width: number; height: number };
type GraphViewBox = { x: number; y: number; width: number; height: number };

type SelectedGraphNodeDetail = {
  inputPayload?: unknown;
  outputPayload?: unknown;
  responseText?: string;
  lastTimestamp?: string;
};

type RAGChatGraphPanelProps = {
  graphThreadId: string;
  graphDefinitionLoading: boolean;
  graphZoom: number;
  graphPanning: boolean;
  graphCanvasSize: GraphCanvasSize;
  graphEffectiveViewBox: GraphViewBox;
  graphContainerRef: RefObject<HTMLDivElement>;
  graphEdgePaths: GraphEdgePath[];
  graphRenderNodes: GraphRenderNode[];
  graphNodeStates: Record<string, NodeRuntimeState>;
  graphLatestMetrics: Record<string, any> | null;
  selectedGraphNodeKey: string | null;
  selectedGraphNodeStatus: NodeRuntimeStatus;
  selectedGraphNodeState?: NodeRuntimeState;
  selectedGraphNodeDetail: SelectedGraphNodeDetail;
  onClose: () => void;
  onZoomOut: () => void;
  onZoomIn: () => void;
  onResetZoom: () => void;
  onPanStart: (event: MouseEvent<HTMLDivElement>) => void;
  onSelectNode: (nodeKey: string) => void;
  resolveEdgeClassName: (edge: GraphDefinition['edges'][number]) => string;
  resolveNodeClassName: (status: NodeRuntimeStatus, selected?: boolean) => string;
  resolveGraphNodeStatus: (nodeKey: string) => NodeRuntimeStatus;
  formatNodeDuration: (durationMs: number) => string;
  formatJsonForDisplay: (value: unknown) => string;
};

export function RAGChatGraphPanel({
  graphThreadId,
  graphDefinitionLoading,
  graphZoom,
  graphPanning,
  graphCanvasSize,
  graphEffectiveViewBox,
  graphContainerRef,
  graphEdgePaths,
  graphRenderNodes,
  graphNodeStates,
  graphLatestMetrics,
  selectedGraphNodeKey,
  selectedGraphNodeStatus,
  selectedGraphNodeState,
  selectedGraphNodeDetail,
  onClose,
  onZoomOut,
  onZoomIn,
  onResetZoom,
  onPanStart,
  onSelectNode,
  resolveEdgeClassName,
  resolveNodeClassName,
  resolveGraphNodeStatus,
  formatNodeDuration,
  formatJsonForDisplay,
}: RAGChatGraphPanelProps) {
  return (
        <aside className="chat-graph-panel absolute inset-y-0 right-0 w-1/2 border-l border-oracle-border bg-white z-10 flex flex-col">
          <div className="px-4 py-[11.5px] border-b border-oracle-border bg-gray-50 flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-oracle-dark-gray text-white flex items-center justify-center">
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
                <path d="M200,152a31.84,31.84,0,0,0-19.53,6.68l-23.11-18A31.65,31.65,0,0,0,160,128c0-.74,0-1.48-.08-2.21l13.23-4.41A32,32,0,1,0,168,104c0,.74,0,1.48.08,2.21l-13.23,4.41A32,32,0,0,0,128,96a32.59,32.59,0,0,0-5.27.44L115.89,81A32,32,0,1,0,96,88a32.59,32.59,0,0,0,5.27-.44l6.84,15.4a31.92,31.92,0,0,0-8.57,39.64L73.83,165.44a32.06,32.06,0,1,0,10.63,12l25.71-22.84a31.91,31.91,0,0,0,37.36-1.24l23.11,18A31.65,31.65,0,0,0,168,184a32,32,0,1,0,32-32Zm0-64a16,16,0,1,1-16,16A16,16,0,0,1,200,88ZM80,56A16,16,0,1,1,96,72,16,16,0,0,1,80,56ZM56,208a16,16,0,1,1,16-16A16,16,0,0,1,56,208Zm56-80a16,16,0,1,1,16,16A16,16,0,0,1,112,128Zm88,72a16,16,0,1,1,16-16A16,16,0,0,1,200,200Z" />
              </svg>
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-oracle-dark-gray truncate">Live Graph</p>
              <p className="text-[11px] text-oracle-medium-gray truncate">
                {graphThreadId ? `Thread: ${graphThreadId}` : 'Waiting for run...'}
              </p>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <button
                type="button"
                className="p-1.5 rounded-md text-oracle-medium-gray hover:bg-black/5 transition-colors"
                onClick={onClose}
                aria-label="Close graph panel"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4 bg-oracle-bg-gray">
            {graphDefinitionLoading && (
              <p className="text-xs text-oracle-medium-gray">Loading graph definition...</p>
            )}
            <div className="rounded-lg border border-gray-200 bg-white p-3">
              <div className="flex items-center justify-between gap-2 mb-2">
                <p className="text-[11px] font-semibold text-oracle-dark-gray uppercase tracking-wide">Graph flow</p>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2 text-[10px] text-oracle-medium-gray">
                    <span className="inline-flex items-center gap-1"><span className="graph-status-dot graph-status-dot--idle" />Idle</span>
                    <span className="inline-flex items-center gap-1"><span className="graph-status-dot graph-status-dot--running" />Running</span>
                    <span className="inline-flex items-center gap-1"><span className="graph-status-dot graph-status-dot--completed" />Completed</span>
                    <span className="inline-flex items-center gap-1"><span className="graph-status-dot graph-status-dot--failed" />Failed</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      className="h-6 w-6 rounded border border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
                      onClick={onZoomOut}
                      title="Zoom out"
                      aria-label="Zoom out"
                    >
                      -
                    </button>
                    <button
                      type="button"
                      className="px-2 h-6 rounded border border-gray-300 bg-white text-[10px] text-gray-700 hover:bg-gray-50"
                      onClick={onResetZoom}
                      title="Reset zoom"
                      aria-label="Reset zoom"
                    >
                      {`${Math.round(graphZoom * 100)}%`}
                    </button>
                    <button
                      type="button"
                      className="h-6 w-6 rounded border border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
                      onClick={onZoomIn}
                      title="Zoom in"
                      aria-label="Zoom in"
                    >
                      +
                    </button>
                  </div>
                </div>
              </div>
              <div
                ref={graphContainerRef}
                className={`rounded-md border border-gray-200 bg-oracle-bg-gray h-[420px] select-none [scrollbar-width:thin] [scrollbar-color:#9CA3AF_transparent] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar]:h-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-gray-300 [&::-webkit-scrollbar-track]:bg-transparent ${
                  graphZoom === 1 ? 'overflow-y-auto overflow-x-hidden' : 'overflow-auto'
                }`}
                onMouseDown={onPanStart}
                style={{ cursor: graphPanning ? 'grabbing' : 'grab' }}
              >
                <div
                  style={{
                    width: graphCanvasSize.width,
                    height: graphCanvasSize.height,
                    minWidth: graphCanvasSize.width,
                    minHeight: graphCanvasSize.height,
                    margin: '0 auto',
                  }}
                >
                  <svg
                    width={graphCanvasSize.width}
                    height={graphCanvasSize.height}
                    viewBox={`${graphEffectiveViewBox.x} ${graphEffectiveViewBox.y} ${graphEffectiveViewBox.width} ${graphEffectiveViewBox.height}`}
                    preserveAspectRatio="xMidYMid meet"
                    className="block"
                  >
                  <defs>
                    <marker id="graphArrowGray" markerWidth="5" markerHeight="5" refX="5" refY="2.5" orient="auto">
                      <path d="M0,0 L5,2.5 L0,5 z" fill="#9CA3AF" />
                    </marker>
                    <marker id="graphArrowBlue" markerWidth="5" markerHeight="5" refX="5" refY="2.5" orient="auto">
                      <path d="M0,0 L5,2.5 L0,5 z" fill="#3B82F6" />
                    </marker>
                    <marker id="graphArrowGreen" markerWidth="5" markerHeight="5" refX="5" refY="2.5" orient="auto">
                      <path d="M0,0 L5,2.5 L0,5 z" fill="#10B981" />
                    </marker>
                    <marker id="graphArrowRose" markerWidth="5" markerHeight="5" refX="5" refY="2.5" orient="auto">
                      <path d="M0,0 L5,2.5 L0,5 z" fill="#E11D48" />
                    </marker>
                  </defs>

                  {graphEdgePaths.map((ep, index) => {
                    const edge = { source: ep.source, target: ep.target, condition: ep.condition };
                    const strokeClass = resolveEdgeClassName(edge);
                    const markerId =
                      strokeClass === 'stroke-blue-500'
                        ? 'graphArrowBlue'
                        : strokeClass === 'stroke-emerald-500'
                        ? 'graphArrowGreen'
                        : strokeClass === 'stroke-rose-500'
                        ? 'graphArrowRose'
                        : 'graphArrowGray';
                    const pathD = ep.points.length >= 2
                      ? `M ${ep.points[0].x} ${ep.points[0].y} ${ep.points.slice(1).map((p) => `L ${p.x} ${p.y}`).join(' ')}`
                      : '';
                    const midIdx = Math.floor(ep.points.length / 2);
                    const labelPt = ep.points[midIdx] || ep.points[0];
                    return (
                      <g key={`${ep.source}-${ep.target}-${index}`}>
                        <path
                          d={pathD}
                          fill="none"
                          className={`${strokeClass} transition-colors`}
                          strokeWidth={2}
                          markerEnd={`url(#${markerId})`}
                        />
                        {ep.condition ? (
                          <text
                            x={labelPt.x}
                            y={labelPt.y - 6}
                            textAnchor="middle"
                            className="fill-oracle-medium-gray text-[10px]"
                          >
                            {ep.condition}
                          </text>
                        ) : null}
                      </g>
                    );
                  })}

                  {graphRenderNodes.map((node) => {
                    const status = resolveGraphNodeStatus(node.key);
                    const nodeState = graphNodeStates[node.key];
                    const isSelected = selectedGraphNodeKey === node.key;
                    const nodeClassName = resolveNodeClassName(status, isSelected);
                    return (
                      <g
                        key={node.key}
                        role="button"
                        tabIndex={0}
                        onMouseDown={(event) => event.stopPropagation()}
                        onClick={() => onSelectNode(node.key)}
                        onKeyDown={(event: KeyboardEvent<SVGGElement>) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            onSelectNode(node.key);
                          }
                        }}
                        style={{ cursor: 'pointer', outline: 'none' }}
                        className="group focus:outline-none focus-visible:outline-none"
                      >
                        <rect
                          x={node.x - node.width / 2}
                          y={node.y - NODE_HEIGHT / 2}
                          width={node.width}
                          height={NODE_HEIGHT}
                          rx={10}
                          className={`${nodeClassName} transition-all duration-200 group-hover:opacity-70`}
                          strokeWidth={1.8}
                        />
                        <text
                          x={node.x}
                          y={node.y - 4}
                          textAnchor="middle"
                          className="fill-current text-[12px] font-semibold"
                        >
                          {node.label}
                        </text>
                        <text
                          x={node.x}
                          y={node.y + 12}
                          textAnchor="middle"
                          className="fill-current text-[10px] opacity-80"
                        >
                          {node.key}
                        </text>
                        {nodeState?.durationMs !== undefined && nodeState.durationMs >= 0 ? (
                          <text
                            x={node.x + node.width / 2 - 6}
                            y={node.y - NODE_HEIGHT / 2 + 12}
                            textAnchor="end"
                            className="fill-current text-[9px] opacity-75"
                          >
                            {formatNodeDuration(nodeState.durationMs)}
                          </text>
                        ) : null}
                      </g>
                    );
                  })}
                </svg>
                </div>
              </div>
              {graphLatestMetrics && (
                <div className="flex flex-wrap items-center gap-2 text-[11px] mt-2">
                  <span className="rounded border border-gray-200 bg-gray-50 px-2 py-0.5 text-oracle-medium-gray">
                    Strategy: <span className="font-semibold text-oracle-dark-gray">{graphLatestMetrics.strategy || '-'}</span>
                  </span>
                  <span className="rounded border border-gray-200 bg-gray-50 px-2 py-0.5 text-oracle-medium-gray">
                    Provider: <span className="font-semibold text-oracle-dark-gray">{graphLatestMetrics.selected_provider || '-'}</span>
                  </span>
                  <span className="rounded border border-gray-200 bg-gray-50 px-2 py-0.5 text-oracle-medium-gray">
                    Evidence: <span className="font-semibold text-oracle-dark-gray">{graphLatestMetrics.evidence_count ?? 0}</span>
                  </span>
                  <span className="rounded border border-gray-200 bg-gray-50 px-2 py-0.5 text-oracle-medium-gray">
                    Citations: <span className="font-semibold text-oracle-dark-gray">{graphLatestMetrics.citation_count ?? 0}</span>
                  </span>
                </div>
              )}
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-3 space-y-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] font-semibold text-oracle-dark-gray uppercase tracking-wide">Node inspector</p>
                {selectedGraphNodeKey ? (
                  <span className="text-[10px] text-oracle-medium-gray rounded border border-gray-200 px-1.5 py-0.5">
                    {selectedGraphNodeKey}
                  </span>
                ) : null}
              </div>

              {!selectedGraphNodeKey ? (
                <p className="text-[11px] text-oracle-light-gray">Select a node in the graph to inspect input and output.</p>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2 text-[11px]">
                    <span className="rounded border border-gray-200 bg-gray-50 px-2 py-0.5 text-oracle-medium-gray">
                      Status: <span className="font-semibold text-oracle-dark-gray">{selectedGraphNodeStatus}</span>
                    </span>
                    {selectedGraphNodeState?.durationMs !== undefined ? (
                      <span className="rounded border border-gray-200 bg-gray-50 px-2 py-0.5 text-oracle-medium-gray">
                        Duration: <span className="font-semibold text-oracle-dark-gray">{formatNodeDuration(selectedGraphNodeState.durationMs)}</span>
                      </span>
                    ) : null}
                    {selectedGraphNodeDetail.lastTimestamp ? (
                      <span className="rounded border border-gray-200 bg-gray-50 px-2 py-0.5 text-oracle-medium-gray">
                        Last event: <span className="font-semibold text-oracle-dark-gray">{new Date(selectedGraphNodeDetail.lastTimestamp).toLocaleTimeString()}</span>
                      </span>
                    ) : null}
                  </div>

                  {selectedGraphNodeDetail.responseText ? (
                    <div className="space-y-1">
                      <p className="text-[11px] font-semibold text-oracle-dark-gray">Response</p>
                      <div className="rounded border border-gray-200 bg-gray-50 p-2 text-[11px] text-oracle-medium-gray max-h-[140px] overflow-auto whitespace-pre-wrap">
                        {selectedGraphNodeDetail.responseText}
                      </div>
                    </div>
                  ) : null}

                  <div className="grid grid-cols-1 gap-2">
                    <div className="space-y-1">
                      <p className="text-[11px] font-semibold text-oracle-dark-gray">Input</p>
                      {selectedGraphNodeDetail.inputPayload === undefined ? (
                        <p className="text-[11px] text-oracle-light-gray">No input payload available.</p>
                      ) : (
                        <pre className="rounded border border-gray-200 bg-gray-50 p-2 text-[11px] text-oracle-medium-gray max-h-[170px] overflow-auto whitespace-pre-wrap break-words">
                          {formatJsonForDisplay(selectedGraphNodeDetail.inputPayload)}
                        </pre>
                      )}
                    </div>
                    <div className="space-y-1">
                      <p className="text-[11px] font-semibold text-oracle-dark-gray">Output</p>
                      {selectedGraphNodeDetail.outputPayload === undefined ? (
                        <p className="text-[11px] text-oracle-light-gray">No output payload available.</p>
                      ) : (
                        <pre className="rounded border border-gray-200 bg-gray-50 p-2 text-[11px] text-oracle-medium-gray max-h-[190px] overflow-auto whitespace-pre-wrap break-words">
                          {formatJsonForDisplay(selectedGraphNodeDetail.outputPayload)}
                        </pre>
                      )}
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </aside>

  );
}
