import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { useAuth } from '../../context/AuthContext';
import { useRAGChat } from '../../context/RAGChatContext';
import { parseChatSelectorsDetailed, type ParsedChatSelectorToken } from '../../lib/chatSelectors';
import { queryKeys } from '../../lib/queryClient';
import {
  type GraphDefinition,
  type GraphRuntimeEvent,
  type RAGScopeOptions,
  type ReasoningResult,
} from '../../services/apiTypes';
import { chatApi } from '../../services/chatApi';
import { improvementApi } from '../../services/improvementApi';
import { ragApi } from '../../services/ragApi';
import { settingsApi } from '../../services/settingsApi';
import {
  buildChatRequestOptionsFromComposer,
  buildComposerTokenPayload,
  buildComposerVisualInlineParts,
  buildEffectiveComposerQuestionText,
  buildSelectorSuggestionGroups,
  insertComposerTokenLabel,
  reconcileComposerTokens,
  removeComposerToken,
  serializeComposerInput,
  type ComposerSelectorState,
  type SelectorSuggestion,
} from './RAGChatPanel.composer';
import {
  buildGraphWithDagre,
  DEFAULT_GRAPH_DEFINITION,
  formatGraphNodeDuration,
  NODE_HEIGHT,
  resolveGraphEdgeClassName,
  resolveGraphNodeClassName,
  resolveGraphRuntimeNodeStatus,
} from './RAGChatPanel.graph';
import {
  cleanPageMarkdownForPreview,
  extractDocumentPageMarkdown,
  stripInlineSourcesSection,
} from './RAGChatPanel.markdown';
import {
  extractNodeResponseText,
  formatJsonForDisplay,
  buildLocalComposerCommandMessages,
  mapCitedSourcesFromMetadata,
  mapReasoningFromMetadata,
  mergeLoadedConversationMessages,
} from './RAGChatPanel.messages';
import { getInitials } from './RAGChatPanel.types';
import type {
  FeedbackKind,
  Message,
  NodeRuntimeState,
  NodeRuntimeStatus,
  Source,
} from './RAGChatPanel.types';
import { ConfirmDeleteModal } from './ConfirmDeleteModal';
import { RAGChatComposer } from './RAGChatComposer';
import { RAGChatGraphPanel } from './RAGChatGraphPanel';
import { RAGChatMessageList } from './RAGChatMessageList';
import { RAGChatSourcePreviewModal } from './RAGChatSourcePreviewModal';

export function RAGChatPanel() {
  const queryClient = useQueryClient();
  const { user, isAuthenticated } = useAuth();
  const sessionScope = user?.user_id ?? 'anonymous';
  const {
    activeConversationId,
    activeConversationTitle,
    filterDocId,
    filterDocName,
    attachConversation,
    openNewConversation,
  } = useRAGChat();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [composerTokens, setComposerTokens] = useState<ParsedChatSelectorToken[]>([]);
  const [composerFocused, setComposerFocused] = useState(false);
  const [composerCaret, setComposerCaret] = useState(0);
  const [composerSelectionEnd, setComposerSelectionEnd] = useState(0);
  const [selectedSuggestionIndex, setSelectedSuggestionIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingStartedAt, setLoadingStartedAt] = useState<number | null>(null);
  const [loadingElapsedSeconds, setLoadingElapsedSeconds] = useState(0);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [isHeaderMenuOpen, setIsHeaderMenuOpen] = useState(false);
  const [renamingConversation, setRenamingConversation] = useState(false);
  const [isInlineRenaming, setIsInlineRenaming] = useState(false);
  const [renameDraft, setRenameDraft] = useState('');
  const [deletingConversation, setDeletingConversation] = useState(false);
  const [isDeleteConfirmOpen, setIsDeleteConfirmOpen] = useState(false);
  const [isSourcePreviewOpen, setIsSourcePreviewOpen] = useState(false);
  const [sourcePreviewTitle, setSourcePreviewTitle] = useState('');
  const [sourcePreviewPageNumber, setSourcePreviewPageNumber] = useState(0);
  const [sourcePreviewImageUri, setSourcePreviewImageUri] = useState('');
  const [sourcePreviewMarkdown, setSourcePreviewMarkdown] = useState('');
  const [sourcePreviewEvidenceSnippet, setSourcePreviewEvidenceSnippet] = useState('');
  const [sourcePreviewLoading, setSourcePreviewLoading] = useState(false);
  const [sourcePreviewImageError, setSourcePreviewImageError] = useState('');
  const [sourcePreviewMarkdownError, setSourcePreviewMarkdownError] = useState('');
  const [isGraphPanelOpen, setIsGraphPanelOpen] = useState(false);
  const [graphRunStatus, setGraphRunStatus] = useState<'idle' | 'running' | 'completed' | 'failed'>('idle');
  const [graphThreadId, setGraphThreadId] = useState('');
  const [graphRunEvents, setGraphRunEvents] = useState<GraphRuntimeEvent[]>([]);
  const [graphNodeStates, setGraphNodeStates] = useState<Record<string, NodeRuntimeState>>({});
  const [selectedGraphNodeKey, setSelectedGraphNodeKey] = useState<string | null>(null);
  const [graphLatestMetrics, setGraphLatestMetrics] = useState<Record<string, any> | null>(null);
  const [graphZoom, setGraphZoom] = useState(1);
  const [graphPan, setGraphPan] = useState({ x: 0, y: 0 });
  const [graphPanning, setGraphPanning] = useState(false);
  const graphPanRef = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null);
  const graphNodeStartMsRef = useRef<Record<string, number>>({});
  const graphRunStartedMsRef = useRef<number | null>(null);
  const graphContainerRef = useRef<HTMLDivElement>(null);
  const [graphContainerSize, setGraphContainerSize] = useState({ width: 522, height: 420 });
  const [messageFeedback, setMessageFeedback] = useState<Record<string, FeedbackKind>>({});
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const headerMenuRef = useRef<HTMLDivElement>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const skipBlurRenameRef = useRef(false);
  const copiedTimeoutRef = useRef<number | null>(null);
  const bootstrappingConversationIdRef = useRef<number | null>(null);
  const composerInputRef = useRef<HTMLTextAreaElement>(null);
  const assistantSettingsQuery = useQuery({
    queryKey: ['settings', 'assistant-name'],
    queryFn: () => settingsApi.get(),
    enabled: isAuthenticated,
    staleTime: 60_000,
  });
  const scopeOptionsQuery = useQuery({
    queryKey: queryKeys.rag.scopeOptions(sessionScope),
    queryFn: () => ragApi.getScopeOptions(),
    enabled: isAuthenticated,
    staleTime: 60_000,
  });
  const graphDefinitionQuery = useQuery({
    queryKey: ['questions-graph-definition'],
    queryFn: () => ragApi.getGraphDefinition(),
    enabled: isAuthenticated && isGraphPanelOpen,
    staleTime: 300_000,
  });

  const graphDefinition = useMemo<GraphDefinition>(() => {
    const payload = graphDefinitionQuery.data?.data;
    if (payload && Array.isArray(payload.nodes) && Array.isArray(payload.edges)) {
      return payload as GraphDefinition;
    }
    return DEFAULT_GRAPH_DEFINITION;
  }, [graphDefinitionQuery.data]);
  const assistantDisplayName = useMemo(() => {
    const resolved = String(assistantSettingsQuery.data?.data?.app?.agent_name || '').trim();
    return resolved || 'Nadia Assist';
  }, [assistantSettingsQuery.data]);
  const scopeOptions = useMemo<RAGScopeOptions>(
    () =>
      (scopeOptionsQuery.data?.data as RAGScopeOptions | undefined) || {
        files: [],
        metadata_fields: [],
        has_metadata: false,
      },
    [scopeOptionsQuery.data]
  );
  const assistantAvatarUrl = useMemo(() => {
    const resolved = String(assistantSettingsQuery.data?.data?.app?.avatar_url || '').trim();
    return resolved || '';
  }, [assistantSettingsQuery.data]);
  const [assistantAvatarImageFailed, setAssistantAvatarImageFailed] = useState(false);
  const showAssistantAvatarImage = Boolean(assistantAvatarUrl) && !assistantAvatarImageFailed;
  const assistantAvatarLetter = useMemo(() => {
    const initials = getInitials(assistantDisplayName);
    return (initials[0] || 'N').toUpperCase();
  }, [assistantDisplayName]);
  const composerRawQuestion = useMemo(
    () => serializeComposerInput(input, composerTokens),
    [input, composerTokens]
  );
  const composerParsedSelectors = useMemo(
    () => parseChatSelectorsDetailed({ question: composerRawQuestion, scopeOptions }),
    [composerRawQuestion, scopeOptions]
  );
  const composerSelectorState = useMemo<ComposerSelectorState>(
    () => ({
      metadataMode: composerParsedSelectors.metadataMode,
      archiveSlugs: composerParsedSelectors.archiveSlugs,
      metadataFields: composerParsedSelectors.metadataFields,
      metadataRequestedExplicitly:
        composerTokens.some((token) => token.kind === 'metadata') ||
        /(^|[\s,;])@metadata\b/i.test(composerRawQuestion),
    }),
    [composerParsedSelectors, composerTokens, composerRawQuestion]
  );
  const composerHasActiveSelection = composerFocused && composerCaret !== composerSelectionEnd;
  const composerVisualInlineParts = useMemo(
    () =>
      buildComposerVisualInlineParts(
        input,
        composerTokens,
        composerCaret,
        composerFocused && !composerHasActiveSelection
      ),
    [input, composerTokens, composerCaret, composerFocused, composerHasActiveSelection]
  );
  const selectorSuggestionState = useMemo(
    () => buildSelectorSuggestionGroups(input, composerCaret, scopeOptions, composerSelectorState, composerTokens),
    [input, composerCaret, scopeOptions, composerSelectorState, composerTokens]
  );
  const selectorSuggestions = useMemo(
    () => selectorSuggestionState.groups.flatMap((group) => group.items),
    [selectorSuggestionState.groups]
  );
  const hasSelectorSuggestions = composerFocused && selectorSuggestions.length > 0;
  const graphNodes = graphDefinition.nodes || [];
  const graphEdges = graphDefinition.edges || [];
  const { nodes: graphRenderNodes, edgePaths: graphEdgePaths } = useMemo(
    () => buildGraphWithDagre(graphNodes, graphEdges),
    [graphNodes, graphEdges]
  );
  const graphViewBox = useMemo(() => {
    if (graphRenderNodes.length === 0) return { x: 0, y: 0, width: 420, height: 900 };
    const nodeMinX = Math.min(...graphRenderNodes.map((node) => node.x - node.width / 2));
    const nodeMinY = Math.min(...graphRenderNodes.map((node) => node.y - NODE_HEIGHT / 2));
    const nodeMaxX = Math.max(...graphRenderNodes.map((node) => node.x + node.width / 2));
    const nodeMaxY = Math.max(...graphRenderNodes.map((node) => node.y + NODE_HEIGHT / 2));
    let minX = nodeMinX;
    let minY = nodeMinY;
    let maxX = nodeMaxX;
    let maxY = nodeMaxY;
    for (const ep of graphEdgePaths) {
      for (const pt of ep.points) {
        minX = Math.min(minX, pt.x);
        minY = Math.min(minY, pt.y);
        maxX = Math.max(maxX, pt.x);
        maxY = Math.max(maxY, pt.y);
      }
    }
    const padding = 100;
    const x = minX - padding;
    const y = minY - padding;
    const width = Math.max(420, Math.round(maxX - minX + 2 * padding));
    const height = Math.max(900, Math.round(maxY - minY + 2 * padding));
    return { x, y, width, height };
  }, [graphRenderNodes, graphEdgePaths]);

  useEffect(() => {
    setGraphPan({ x: 0, y: 0 });
  }, [graphRenderNodes]);

  useEffect(() => {
    const el = graphContainerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          setGraphContainerSize({ width: Math.round(width), height: Math.round(height) });
        }
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [isGraphPanelOpen]);

  const graphCanvasSize = useMemo(() => {
    const width = Math.round(graphContainerSize.width);
    const aspectRatio = graphViewBox.height / graphViewBox.width;
    const height = Math.round(width * aspectRatio);
    return { width, height };
  }, [graphViewBox, graphContainerSize]);

  const graphEffectiveViewBox = useMemo(() => {
    const zoom = Math.max(0.6, Math.min(4, graphZoom));
    const scale = 1 / zoom;
    const w = graphViewBox.width * scale;
    const h = graphViewBox.height * scale;
    const x = graphViewBox.x - (w - graphViewBox.width) / 2 + graphPan.x;
    const y = graphViewBox.y - (h - graphViewBox.height) / 2 + graphPan.y;
    return { x, y, width: w, height: h };
  }, [graphViewBox, graphZoom, graphPan]);

  useEffect(() => {
    if (!isGraphPanelOpen) {
      setSelectedGraphNodeKey(null);
      return;
    }
    if (selectedGraphNodeKey && graphRenderNodes.some((node) => node.key === selectedGraphNodeKey)) {
      return;
    }
    const preferredNode = graphRenderNodes.find((node) => node.key !== 'START' && node.key !== 'END');
    setSelectedGraphNodeKey(preferredNode?.key || graphRenderNodes[0]?.key || null);
  }, [isGraphPanelOpen, graphRenderNodes, selectedGraphNodeKey]);

  const selectedGraphNodeEvents = useMemo(() => {
    if (!selectedGraphNodeKey) return [];
    return graphRunEvents.filter((event) => String(event?.node_key || '').trim() === selectedGraphNodeKey);
  }, [graphRunEvents, selectedGraphNodeKey]);

  const selectedGraphNodeDetail = useMemo(() => {
    if (!selectedGraphNodeKey) {
      return { inputPayload: undefined as unknown, outputPayload: undefined as unknown, responseText: '', lastTimestamp: '' };
    }
    const latestFirst = [...selectedGraphNodeEvents].reverse();
    const startedEvent = latestFirst.find((event) => {
      const status = String(event?.status || '').toLowerCase();
      return status === 'started' || status === 'running';
    });
    const completedEvent = latestFirst.find((event) => {
      const status = String(event?.status || '').toLowerCase();
      return status === 'completed' || status === 'failed' || status === 'snapshot';
    });
    const startedPayload = startedEvent?.payload as Record<string, unknown> | undefined;
    const inputPayload =
      startedPayload && typeof startedPayload === 'object' && 'input' in startedPayload
        ? startedPayload.input
        : startedEvent?.payload;

    const completedPayload = completedEvent?.payload as Record<string, unknown> | undefined;
    const outputPayload =
      completedEvent?.state_patch && Object.keys(completedEvent.state_patch).length > 0
        ? completedEvent.state_patch
        : completedPayload && typeof completedPayload === 'object' && 'result' in completedPayload
        ? completedPayload.result
        : completedEvent?.payload;

    const responseText = extractNodeResponseText(outputPayload) || extractNodeResponseText(completedEvent?.payload);
    const lastTimestamp = String((latestFirst[0]?.timestamp || '') as string);
    return { inputPayload, outputPayload, responseText, lastTimestamp };
  }, [selectedGraphNodeEvents, selectedGraphNodeKey]);

  const resolveGraphNodeStatus = (nodeKey: string): NodeRuntimeStatus =>
    resolveGraphRuntimeNodeStatus(nodeKey, graphRunStatus, graphNodeStates);

  const resolveNodeClassName = (status: NodeRuntimeStatus, selected?: boolean) =>
    resolveGraphNodeClassName(status, selected);

  const resolveEdgeClassName = (edge: GraphDefinition['edges'][number]) =>
    resolveGraphEdgeClassName(edge, resolveGraphNodeStatus);

  const formatNodeDuration = formatGraphNodeDuration;

  const resetGraphRuntimeState = () => {
    const nextState: Record<string, NodeRuntimeState> = {};
    for (const node of graphNodes) {
      nextState[node.key] = { status: 'idle' };
    }
    graphNodeStartMsRef.current = {};
    graphRunStartedMsRef.current = null;
    setGraphNodeStates(nextState);
    setGraphRunEvents([]);
    setGraphRunStatus('idle');
    setGraphThreadId('');
    setGraphLatestMetrics(null);
  };
  const adjustGraphZoom = useCallback((delta: number) => {
    setGraphZoom((prev) => {
      const next = prev + delta;
      return Math.min(4, Math.max(0.6, Math.round(next * 100) / 100));
    });
  }, []);
  const resetGraphZoom = () => {
    setGraphZoom(1);
    setGraphPan({ x: 0, y: 0 });
  };

  const handleGraphWheel = useCallback(
    (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.1 : 0.1;
      adjustGraphZoom(delta);
    },
    [adjustGraphZoom]
  );

  useEffect(() => {
    if (!isGraphPanelOpen) return;
    const el = graphContainerRef.current;
    if (!el) return;
    el.addEventListener('wheel', handleGraphWheel, { passive: false });
    return () => el.removeEventListener('wheel', handleGraphWheel);
  }, [handleGraphWheel, isGraphPanelOpen]);

  const handleGraphPanStart = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    graphPanRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      panX: graphPan.x,
      panY: graphPan.y,
    };
    setGraphPanning(true);
  };

  useEffect(() => {
    if (!graphPanning) return;
    const onMove = (e: MouseEvent) => {
      if (!graphPanRef.current) return;
      const dx = e.clientX - graphPanRef.current.startX;
      const dy = e.clientY - graphPanRef.current.startY;
      setGraphPan({
        x: graphPanRef.current.panX - dx,
        y: graphPanRef.current.panY - dy,
      });
    };
    const onUp = () => {
      graphPanRef.current = null;
      setGraphPanning(false);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [graphPanning]);

  const applyGraphRuntimeEvent = (event: GraphRuntimeEvent) => {
    setGraphRunEvents((prev) => [...prev.slice(-199), event]);
    const eventTsMs = event?.timestamp ? new Date(event.timestamp).getTime() : NaN;
    const parsedEventMs = Number.isNaN(eventTsMs) ? null : eventTsMs;
    const threadId = String(event?.thread_id || '').trim();
    if (threadId) {
      setGraphThreadId(threadId);
    }
    const nodeKey = String(event?.node_key || '').trim();
    if (nodeKey) {
      setGraphNodeStates((prev) => {
        const current = prev[nodeKey] || { status: 'idle' as NodeRuntimeStatus };
        const eventStatus = String(event?.status || '').toLowerCase();
        const isRunningEvent = eventStatus === 'started' || eventStatus === 'running';
        const isCompletedEvent = eventStatus === 'completed' || eventStatus === 'snapshot';
        const isFailedEvent = eventStatus === 'failed';
        let nextStatus: NodeRuntimeStatus = current.status;
        if (isRunningEvent) nextStatus = 'running';
        else if (isCompletedEvent) nextStatus = 'completed';
        else if (isFailedEvent) nextStatus = 'failed';

        if (isRunningEvent && parsedEventMs !== null && current.startedAt === undefined) {
          graphNodeStartMsRef.current[nodeKey] = parsedEventMs;
        }

        const startedAt = current.startedAt || (isRunningEvent ? event.timestamp : undefined);
        const endedAt = (isCompletedEvent || isFailedEvent) ? current.endedAt || event.timestamp : current.endedAt;
        let durationMs = current.durationMs;
        if (durationMs === undefined) {
          if (typeof event.duration_ms === 'number' && event.duration_ms >= 0) {
            durationMs = event.duration_ms;
          } else if ((isCompletedEvent || isFailedEvent) && parsedEventMs !== null) {
            const startedMs = graphNodeStartMsRef.current[nodeKey];
            if (typeof startedMs === 'number') {
              durationMs = Math.max(0, parsedEventMs - startedMs);
            } else if (startedAt && endedAt) {
              const diff = new Date(endedAt).getTime() - new Date(startedAt).getTime();
              durationMs = Number.isNaN(diff) ? current.durationMs : Math.max(0, diff);
            }
          } else if (startedAt && endedAt) {
            const diff = new Date(endedAt).getTime() - new Date(startedAt).getTime();
            durationMs = Number.isNaN(diff) ? current.durationMs : Math.max(0, diff);
          }
        }

        if ((isCompletedEvent || isFailedEvent) && parsedEventMs !== null) {
          delete graphNodeStartMsRef.current[nodeKey];
        }
        return {
          ...prev,
          [nodeKey]: {
            status: nextStatus,
            startedAt,
            endedAt,
            durationMs,
            lastEventType: String(event?.event_type || ''),
            error: nextStatus === 'failed' ? String(event?.error || current.error || '') : current.error,
          },
        };
      });
    }
    if (event.event_type === 'run_started') {
      if (parsedEventMs !== null) {
        graphRunStartedMsRef.current = parsedEventMs;
        graphNodeStartMsRef.current.classify_intent = parsedEventMs;
      }
      setGraphRunStatus('running');
      setGraphLatestMetrics(null);
      return;
    }
    if (event.event_type === 'run_completed') {
      setGraphRunStatus('completed');
      setGraphNodeStates((prev) => {
        const currentEnd = prev.END || { status: 'completed' as NodeRuntimeStatus };
        const totalDuration = parsedEventMs !== null && graphRunStartedMsRef.current !== null
          ? Math.max(0, parsedEventMs - graphRunStartedMsRef.current)
          : currentEnd.durationMs ?? 0;
        return {
          ...prev,
          END: {
            ...currentEnd,
            status: 'completed',
            endedAt: event.timestamp || currentEnd.endedAt,
            durationMs: totalDuration,
          },
        };
      });
      const execution = event.execution;
      if (execution && typeof execution === 'object') {
        setGraphLatestMetrics({
          strategy: String(execution?.strategy || ''),
          answer_mode: String(execution?.answer_mode || ''),
          evidence_count: Array.isArray(execution?.evidence) ? execution.evidence.length : 0,
          citation_count: Array.isArray(execution?.answer?.citation_source_numbers)
            ? execution.answer.citation_source_numbers.length
            : 0,
          selected_provider: String(execution?.selected_provider || ''),
        });
      }
      return;
    }
    if (event.event_type === 'run_failed') {
      setGraphRunStatus('failed');
      setGraphNodeStates((prev) => {
        const currentEnd = prev.END || { status: 'failed' as NodeRuntimeStatus };
        const totalDuration = parsedEventMs !== null && graphRunStartedMsRef.current !== null
          ? Math.max(0, parsedEventMs - graphRunStartedMsRef.current)
          : currentEnd.durationMs ?? 0;
        return {
          ...prev,
          END: {
            ...currentEnd,
            status: 'failed',
            endedAt: event.timestamp || currentEnd.endedAt,
            durationMs: totalDuration,
          },
        };
      });
    }
  };

  const selectedGraphNodeState = selectedGraphNodeKey ? graphNodeStates[selectedGraphNodeKey] : undefined;
  const selectedGraphNodeStatus: NodeRuntimeStatus = selectedGraphNodeKey
    ? resolveGraphNodeStatus(selectedGraphNodeKey)
    : 'idle';

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages]);

  useEffect(() => {
    if (!isGraphPanelOpen) return;
    if (Object.keys(graphNodeStates).length > 0) return;
    const nextState: Record<string, NodeRuntimeState> = {};
    for (const node of graphNodes) {
      nextState[node.key] = { status: 'idle' };
    }
    setGraphNodeStates(nextState);
  }, [isGraphPanelOpen, graphNodes, graphNodeStates]);

  useEffect(() => {
    if (!loading || loadingStartedAt === null) {
      setLoadingElapsedSeconds(0);
      return;
    }
    const updateElapsed = () => {
      setLoadingElapsedSeconds(Math.max(0, Math.floor((Date.now() - loadingStartedAt) / 1000)));
    };
    updateElapsed();
    const intervalId = window.setInterval(updateElapsed, 1000);
    return () => {
      window.clearInterval(intervalId);
    };
  }, [loading, loadingStartedAt]);

  useEffect(() => {
    const handleOutsideClick = (event: MouseEvent) => {
      if (!isHeaderMenuOpen) return;
      const target = event.target as Node | null;
      if (headerMenuRef.current && target && !headerMenuRef.current.contains(target)) {
        setIsHeaderMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
    };
  }, [isHeaderMenuOpen]);

  useEffect(() => {
    setIsHeaderMenuOpen(false);
    setIsInlineRenaming(false);
  }, [activeConversationId]);

  useEffect(() => {
    setAssistantAvatarImageFailed(false);
  }, [assistantAvatarUrl]);

  useEffect(() => {
    if (!isInlineRenaming) return;
    const timeoutId = window.setTimeout(() => {
      titleInputRef.current?.focus();
      titleInputRef.current?.select();
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [isInlineRenaming]);

  useEffect(() => {
    let cancelled = false;
    const loadConversationMessages = async () => {
      if (!activeConversationId) {
        bootstrappingConversationIdRef.current = null;
        setLoadingConversation(false);
        setMessages([]);
        return;
      }
      if (
        bootstrappingConversationIdRef.current !== null &&
        bootstrappingConversationIdRef.current !== activeConversationId
      ) {
        bootstrappingConversationIdRef.current = null;
      }
      const isBootstrappingConversation =
        bootstrappingConversationIdRef.current === activeConversationId;
      setLoadingConversation(true);
      if (!isBootstrappingConversation) {
        setMessages([]);
      }
      try {
        const response = await chatApi.getMessages(activeConversationId);
        const loaded = (response.data?.messages || []).map((item: any) => {
          const metadata = item.retrieval_metadata || {};
          const citedSources = mapCitedSourcesFromMetadata(metadata);
          return {
            messageId: String(item.message_id),
            role: item.role === 'user' ? 'user' : 'assistant',
            text: stripInlineSourcesSection(String(item.content || '')),
            timestamp: new Date(item.created_at),
            modelUsed: String(item.model_used || ''),
            citedSources,
            reasoning: mapReasoningFromMetadata(metadata),
            telemetry: metadata,
          };
        }) as Message[];
        if (!cancelled) {
          setMessages((previousMessages) => {
            if (isBootstrappingConversation) {
              if (loaded.length === 0 && previousMessages.length > 0) {
                return previousMessages;
              }
              return mergeLoadedConversationMessages(loaded, previousMessages);
            }
            return loaded;
          });
        }
        if (!cancelled && isBootstrappingConversation && loaded.length > 0) {
          bootstrappingConversationIdRef.current = null;
        }
      } catch {
        if (!cancelled) {
          if (!isBootstrappingConversation) {
            setMessages([]);
          }
        }
      } finally {
        if (!cancelled) {
          setLoadingConversation(false);
        }
      }
    };
    loadConversationMessages();
    return () => {
      cancelled = true;
    };
  }, [activeConversationId]);

  useEffect(() => {
    return () => {
      if (copiedTimeoutRef.current !== null) {
        window.clearTimeout(copiedTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (selectedSuggestionIndex < selectorSuggestions.length) return;
    setSelectedSuggestionIndex(0);
  }, [selectedSuggestionIndex, selectorSuggestions.length]);

  useEffect(() => {
    const textarea = composerInputRef.current;
    if (!textarea) return;
    const maxHeight = 224;
    textarea.style.height = 'auto';
    const nextHeight = Math.min(textarea.scrollHeight, maxHeight);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? 'auto' : 'hidden';
  }, [input, composerTokens.length]);

  const focusComposerInput = useCallback((caretPosition?: number) => {
    window.requestAnimationFrame(() => {
      const textarea = composerInputRef.current;
      if (!textarea) return;
      const nextCaret = Math.max(
        0,
        Math.min(
          typeof caretPosition === 'number' ? caretPosition : textarea.value.length,
          textarea.value.length
        )
      );
      textarea.focus({ preventScroll: true });
      textarea.setSelectionRange(nextCaret, nextCaret);
      setComposerFocused(true);
      setComposerCaret(nextCaret);
      setComposerSelectionEnd(nextCaret);
    });
  }, []);

  if (!isAuthenticated || !user) return null;

  const userInitials = getInitials(user.name || 'U');
  const activeScopeFileIds =
    filterDocId && String(filterDocId).trim() ? [String(filterDocId).trim()] : undefined;
  const activeScopeLabel = filterDocName || (filterDocId ? `document ${filterDocId}` : null);
  const promptPlaceholder = activeScopeLabel
    ? `Ask anything about ${activeScopeLabel}`
    : 'Ask anything across all your documents';
  const composerPlaceholder = activeScopeLabel
    ? `Search within ${activeScopeLabel}...`
    : 'Search across all your documents...';
  const scopeSubtitle = activeScopeLabel
    ? `Scoped to ${activeScopeLabel}.`
    : 'Search across all documents you can access. Mention a code like RM797 to narrow scope automatically.';
  const isInitialCentered =
    !activeConversationId &&
    messages.length === 0 &&
    !loading &&
    !loadingConversation;

  const updateComposerCaret = useCallback(() => {
    const textarea = composerInputRef.current;
    const selectionStart = textarea?.selectionStart;
    const selectionEnd = textarea?.selectionEnd;
    setComposerCaret(typeof selectionStart === 'number' ? selectionStart : input.length);
    setComposerSelectionEnd(typeof selectionEnd === 'number' ? selectionEnd : input.length);
  }, [input.length]);

  const handleComposerChange = useCallback(
    (value: string) => {
      setComposerTokens((current) => reconcileComposerTokens(input, value, current));
      setInput(value);
      window.requestAnimationFrame(() => {
        const textarea = composerInputRef.current;
        const selectionStart = textarea?.selectionStart;
        const selectionEnd = textarea?.selectionEnd;
        setComposerCaret(typeof selectionStart === 'number' ? selectionStart : value.length);
        setComposerSelectionEnd(typeof selectionEnd === 'number' ? selectionEnd : value.length);
      });
      setSelectedSuggestionIndex(0);
    },
    [input]
  );

  const removeComposerChip = useCallback(
    (token: ParsedChatSelectorToken) => {
      const { nextValue, nextCaret } = removeComposerToken(input, token.start, token.end);
      const remainingTokens = reconcileComposerTokens(input, nextValue, composerTokens).filter(
        (candidate) =>
          !(
            candidate.kind === token.kind &&
            candidate.raw === token.raw &&
            candidate.start === token.start &&
            candidate.end === token.end
          )
      );
      setInput(nextValue);
      setComposerTokens(remainingTokens);
      setSelectedSuggestionIndex(0);
      window.requestAnimationFrame(() => {
        composerInputRef.current?.focus();
        composerInputRef.current?.setSelectionRange(nextCaret, nextCaret);
        setComposerCaret(nextCaret);
        setComposerSelectionEnd(nextCaret);
      });
    },
    [input, composerTokens]
  );

  const applySelectorSuggestion = useCallback(
    (suggestion: SelectorSuggestion) => {
      const context = selectorSuggestionState.context;
      if (!context) return;
      const tokenPayload = buildComposerTokenPayload(suggestion);
      const { nextValue, tokenStart, tokenEnd, nextCaret } = insertComposerTokenLabel(
        input,
        context.start,
        context.end,
        tokenPayload.label,
        suggestion.kind
      );
      const nextTokens = [
        ...reconcileComposerTokens(input, nextValue, composerTokens),
        {
          ...tokenPayload,
          start: tokenStart,
          end: tokenEnd,
        },
      ].sort((left, right) => left.start - right.start);
      setInput(nextValue);
      setComposerTokens(nextTokens);
      setSelectedSuggestionIndex(0);
      window.requestAnimationFrame(() => {
        composerInputRef.current?.focus();
        composerInputRef.current?.setSelectionRange(nextCaret, nextCaret);
        setComposerCaret(nextCaret);
        setComposerSelectionEnd(nextCaret);
      });
    },
    [input, composerTokens, selectorSuggestionState.context]
  );

  const handleSearch = useCallback(async () => {
    const composerQuestion = composerRawQuestion.trim();
    if (!composerQuestion || loading) return;
    const localCommandMessages = buildLocalComposerCommandMessages(composerQuestion, scopeOptions);
    if (localCommandMessages) {
      const createdAt = new Date();
      setInput('');
      setComposerTokens([]);
      setComposerCaret(0);
      setComposerSelectionEnd(0);
      setSelectedSuggestionIndex(0);
      setMessages((prev) => [
        ...prev,
        {
          messageId: `local-user-command-${createdAt.getTime()}`,
          role: 'user',
          text: localCommandMessages.userText,
          timestamp: createdAt,
          localOnly: true,
        },
        {
          messageId: `local-assistant-command-${createdAt.getTime()}`,
          role: 'assistant',
          text: localCommandMessages.assistantText,
          timestamp: new Date(createdAt.getTime() + 1),
          localOnly: true,
        },
      ]);
      focusComposerInput(0);
      return;
    }
    const requestBuild = buildChatRequestOptionsFromComposer(
      composerQuestion,
      scopeOptions,
      composerSelectorState
    );
    const effectiveQuestionText = buildEffectiveComposerQuestionText(requestBuild);
    if (effectiveQuestionText.length < 3) {
      setMessages((prev) => [
        ...prev,
        {
          messageId: `local-error-${Date.now()}`,
          role: 'assistant',
          text: 'La consulta necesita texto o selectores validos de @metadata, /file: o /col:.',
          error: 'La consulta necesita texto o selectores validos de @metadata, /file: o /col:.',
          timestamp: new Date(),
        },
      ]);
      focusComposerInput(input.length);
      return;
    }
    setInput('');
    setComposerTokens([]);
    setComposerCaret(0);
    setComposerSelectionEnd(0);
    setSelectedSuggestionIndex(0);
    const userMessage: Message = {
      messageId: `local-user-${Date.now()}`,
      role: 'user',
      text: composerQuestion,
      timestamp: new Date(),
      telemetry: {
        metadata_mode: requestBuild.requestOptions.metadata_mode,
        requested_archive_slugs: requestBuild.selectors.archiveSlugs,
        requested_metadata_fields: requestBuild.selectors.metadataFields,
        metadata_requested_explicitly: requestBuild.metadataRequestedExplicitly,
      },
    };
    setMessages((prev) => [...prev, userMessage]);
    setLoading(true);
    setLoadingStartedAt(Date.now());
    setLoadingElapsedSeconds(0);
    resetGraphRuntimeState();
    setGraphRunStatus('running');

    let conversationId: number | undefined = activeConversationId ?? undefined;
    try {
      if (!conversationId) {
        const generatedTitle =
          effectiveQuestionText.length > 80
            ? `${effectiveQuestionText.slice(0, 80)}...`
            : effectiveQuestionText;
        const created = await chatApi.createConversation(generatedTitle);
        conversationId = Number(created.data.conversation_id);
        bootstrappingConversationIdRef.current = conversationId;
        attachConversation(conversationId, created.data.title);
        queryClient.invalidateQueries({ queryKey: queryKeys.chats.all(sessionScope) });
      }

      const history = messages
        .filter((message) => !message.localOnly)
        .slice(-20)
        .map((m) => ({ role: m.role, content: m.text }));
      const requestOptions = requestBuild.requestOptions;
      const res = await ragApi.chatStream(
        composerQuestion,
        activeScopeFileIds,
        history,
        conversationId,
        requestOptions,
        (event) => {
          applyGraphRuntimeEvent(event);
        }
      );
      const data = res.data as {
        success?: boolean;
        reply?: string;
        citedSources?: Source[];
        model_used?: string;
        reasoning?: ReasoningResult;
        telemetry?: Record<string, any>;
      };
      const reply = data?.reply ?? '';
      const citedSources = data?.citedSources ?? [];
      setMessages((prev) => [
        ...prev,
        {
          messageId: `local-assistant-${Date.now()}`,
          role: 'assistant',
          text: stripInlineSourcesSection(reply || 'No response received.'),
          timestamp: new Date(),
          modelUsed: data?.model_used || '',
          citedSources,
          reasoning: data?.reasoning,
          telemetry: data?.telemetry,
        },
      ]);
      queryClient.invalidateQueries({ queryKey: queryKeys.chats.all(sessionScope) });
      if (conversationId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.chats.messages(sessionScope, conversationId) });
      }
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Chat error.';
      setGraphRunStatus('failed');
      applyGraphRuntimeEvent({
        event_type: 'run_failed',
        status: 'failed',
        node_key: '',
        error: String(msg),
        timestamp: new Date().toISOString(),
      });
      setMessages((prev) => [
        ...prev,
        {
          messageId: `local-error-${Date.now()}`,
          role: 'assistant',
          text: msg,
          error: msg,
          timestamp: new Date(),
        },
      ]);
    } finally {
      setLoading(false);
      setLoadingStartedAt(null);
      focusComposerInput(0);
    }
  }, [
    activeConversationId,
    activeScopeFileIds,
    attachConversation,
    composerRawQuestion,
    loading,
    messages,
    queryClient,
    composerSelectorState,
    focusComposerInput,
    input.length,
    scopeOptions,
    sessionScope,
  ]);

  const handleComposerKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === 'Backspace' && !event.altKey && !event.ctrlKey && !event.metaKey) {
        const selectionStart = composerInputRef.current?.selectionStart;
        const selectionEnd = composerInputRef.current?.selectionEnd;
        if (
          typeof selectionStart === 'number' &&
          typeof selectionEnd === 'number' &&
          selectionStart === selectionEnd
        ) {
          const tokenToRemove = [...composerTokens]
            .reverse()
            .find((token) => token.end === selectionStart);
          if (tokenToRemove) {
            event.preventDefault();
            removeComposerChip(tokenToRemove);
            return;
          }
        }
      }
      if (hasSelectorSuggestions) {
        if (event.key === 'ArrowDown') {
          event.preventDefault();
          setSelectedSuggestionIndex((current) => (current + 1) % selectorSuggestions.length);
          return;
        }
        if (event.key === 'ArrowUp') {
          event.preventDefault();
          setSelectedSuggestionIndex((current) =>
            current <= 0 ? selectorSuggestions.length - 1 : current - 1
          );
          return;
        }
        if ((event.key === 'Enter' && !event.shiftKey) || (event.key === 'Tab' && !event.shiftKey)) {
          event.preventDefault();
          applySelectorSuggestion(selectorSuggestions[selectedSuggestionIndex] || selectorSuggestions[0]);
          return;
        }
        if (event.key === 'Escape') {
          event.preventDefault();
          setComposerFocused(false);
          setSelectedSuggestionIndex(0);
          return;
        }
      }
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        void handleSearch();
      }
    },
    [
      applySelectorSuggestion,
      composerTokens,
      handleSearch,
      hasSelectorSuggestions,
      removeComposerChip,
      selectedSuggestionIndex,
      selectorSuggestions,
    ]
  );

  const renderComposer = (placeholder: string) => (
    <RAGChatComposer
      placeholder={placeholder}
      input={input}
      loading={loading}
      inputRef={composerInputRef}
      inlineParts={composerVisualInlineParts}
      showOverlay={Boolean(input) && composerTokens.length > 0 && !composerHasActiveSelection}
      showSuggestions={hasSelectorSuggestions}
      suggestionGroups={selectorSuggestionState.groups}
      selectedSuggestionIndex={selectedSuggestionIndex}
      onInputChange={handleComposerChange}
      onInputFocus={() => {
        setComposerFocused(true);
        updateComposerCaret();
      }}
      onInputBlur={() => {
        setComposerFocused(false);
        setSelectedSuggestionIndex(0);
      }}
      onCaretUpdate={updateComposerCaret}
      onInputKeyDown={handleComposerKeyDown}
      onSearch={() => void handleSearch()}
      onApplySuggestion={applySelectorSuggestion}
    />
  );

  const handleDeleteConversation = async () => {
    if (!activeConversationId || deletingConversation) return;
    setDeletingConversation(true);
    try {
      await chatApi.deleteConversation(activeConversationId);
      queryClient.invalidateQueries({ queryKey: queryKeys.chats.all(sessionScope) });
      queryClient.removeQueries({ queryKey: queryKeys.chats.messages(sessionScope, activeConversationId) });
      setMessages([]);
      openNewConversation();
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          messageId: `local-error-${Date.now()}`,
          role: 'assistant',
          text: 'Failed to delete chat.',
          error: 'Failed to delete chat.',
          timestamp: new Date(),
        },
      ]);
    } finally {
      setDeletingConversation(false);
      setIsHeaderMenuOpen(false);
      setIsDeleteConfirmOpen(false);
    }
  };

  const startInlineRename = () => {
    if (!activeConversationId || renamingConversation || deletingConversation) return;
    setRenameDraft(activeConversationTitle || 'New chat');
    setIsInlineRenaming(true);
    setIsHeaderMenuOpen(false);
  };

  const submitInlineRename = async () => {
    if (!activeConversationId || renamingConversation) return;
    const currentTitle = activeConversationTitle || 'New chat';
    const normalizedTitle = renameDraft.trim();
    if (!normalizedTitle || normalizedTitle === currentTitle) {
      setRenameDraft(currentTitle);
      setIsInlineRenaming(false);
      return;
    }
    setRenamingConversation(true);
    try {
      await chatApi.renameConversation(activeConversationId, normalizedTitle);
      attachConversation(activeConversationId, normalizedTitle);
      queryClient.invalidateQueries({ queryKey: queryKeys.chats.all(sessionScope) });
      queryClient.invalidateQueries({ queryKey: queryKeys.chats.messages(sessionScope, activeConversationId) });
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          messageId: `local-error-${Date.now()}`,
          role: 'assistant',
          text: 'Failed to rename chat.',
          error: 'Failed to rename chat.',
          timestamp: new Date(),
        },
      ]);
      setRenameDraft(currentTitle);
    } finally {
      setRenamingConversation(false);
      setIsInlineRenaming(false);
      setIsHeaderMenuOpen(false);
    }
  };

  const cancelInlineRename = () => {
    skipBlurRenameRef.current = true;
    setRenameDraft(activeConversationTitle || 'New chat');
    setIsInlineRenaming(false);
  };

  const handleOpenSourcePreview = async (source: Source) => {
    if (!source.file_id || !source.page_number) return;
    const pageNumber = Number(source.page_number);
    setIsSourcePreviewOpen(true);
    setSourcePreviewTitle(source.name);
    setSourcePreviewPageNumber(Number.isFinite(pageNumber) ? pageNumber : 0);
    setSourcePreviewImageUri('');
    setSourcePreviewMarkdown('');
    setSourcePreviewEvidenceSnippet(String(source.snippet || '').trim());
    setSourcePreviewImageError('');
    setSourcePreviewMarkdownError('');
    setSourcePreviewLoading(true);

    const imageRequest = ragApi.getDocumentPageImage(source.file_id, source.page_number);
    const markdownRequest = ragApi.getDocumentMarkdown(String(source.file_id));
    const [imageResult, markdownResult] = await Promise.allSettled([imageRequest, markdownRequest]);

    if (imageResult.status === 'fulfilled') {
      const imageUri = String(imageResult.value?.data?.data_uri || '').trim();
      if (imageUri) {
        setSourcePreviewImageUri(imageUri);
      } else {
        setSourcePreviewImageError('No image data available for this source.');
      }
    } else {
      const error = imageResult.reason as any;
      const message =
        error?.response?.data?.detail || error?.message || 'Could not load source page image.';
      setSourcePreviewImageError(String(message));
    }

    if (markdownResult.status === 'fulfilled') {
      const markdown = String(markdownResult.value?.data?.markdown ?? '');
      const pageMarkdown = cleanPageMarkdownForPreview(extractDocumentPageMarkdown(markdown, source.page_number));
      setSourcePreviewMarkdown(pageMarkdown || '_No Markdown content found for this page._');
    } else {
      const error = markdownResult.reason as any;
      const message =
        error?.response?.data?.detail || error?.message || 'Could not load source Markdown.';
      setSourcePreviewMarkdownError(String(message));
    }

    setSourcePreviewLoading(false);
  };

  const copySourcePreviewMarkdown = () => {
    if (!sourcePreviewMarkdown || sourcePreviewMarkdownError) return;
    navigator.clipboard.writeText(sourcePreviewMarkdown);
    setCopiedMessageId('source-preview-markdown');
    if (copiedTimeoutRef.current) {
      window.clearTimeout(copiedTimeoutRef.current);
    }
    copiedTimeoutRef.current = window.setTimeout(() => setCopiedMessageId(null), 1500);
  };

  const recordFeedbackEvent = (payload: Record<string, any>) => {
    void improvementApi
      .recordFeedback({
        event_type: String(payload.type || payload.event_type || ''),
        value: String(payload.value || ''),
        conversation_id: payload.conversation_id ?? null,
        trace_id: String(payload.trace_id || '').trim() || null,
        assistant_message_id: String(payload.assistant_message_id || ''),
        user_prompt: String(payload.user_prompt || ''),
        assistant_answer: String(payload.assistant_answer || ''),
        metadata: payload.metadata && typeof payload.metadata === 'object' ? payload.metadata : {},
      })
      .catch(() => undefined);
  };

  const resolveRelatedUserPrompt = (assistantIndex: number): string => {
    for (let idx = assistantIndex - 1; idx >= 0; idx -= 1) {
      if (messages[idx]?.role === 'user') {
        return String(messages[idx]?.text || '');
      }
    }
    return '';
  };

  const handleMessageFeedback = (message: Message, messageIndex: number, kind: FeedbackKind) => {
    if (message.role !== 'assistant' || message.error) return;
    const alreadySelected = messageFeedback[message.messageId] === kind;
    const userPrompt = resolveRelatedUserPrompt(messageIndex);
    setMessageFeedback((prev) => {
      const next = { ...prev };
      if (alreadySelected) {
        delete next[message.messageId];
      } else {
        next[message.messageId] = kind;
      }
      return next;
    });
    recordFeedbackEvent({
      type: 'answer_feedback',
      value: alreadySelected ? 'cleared' : kind,
      conversation_id: activeConversationId ?? null,
      trace_id: String(message.telemetry?.trace_id || ''),
      assistant_message_id: message.messageId,
      user_prompt: userPrompt,
      assistant_answer: message.text,
      metadata: {
        answerability_route: String(message.telemetry?.answerability_route || ''),
        cited_sources_count: Number(message.telemetry?.cited_sources_count || 0),
      },
    });
  };

  const handleCopyAssistantAnswer = async (message: Message, messageIndex: number) => {
    if (message.role !== 'assistant') return;
    const userPrompt = resolveRelatedUserPrompt(messageIndex);
    try {
      await navigator.clipboard.writeText(message.text || '');
      setCopiedMessageId(message.messageId);
      if (copiedTimeoutRef.current !== null) {
        window.clearTimeout(copiedTimeoutRef.current);
      }
      copiedTimeoutRef.current = window.setTimeout(() => {
        setCopiedMessageId(null);
        copiedTimeoutRef.current = null;
      }, 1400);
      recordFeedbackEvent({
        type: 'answer_copy',
        value: 'copied',
        conversation_id: activeConversationId ?? null,
        trace_id: String(message.telemetry?.trace_id || ''),
        assistant_message_id: message.messageId,
        user_prompt: userPrompt,
        assistant_answer: message.text,
        metadata: {
          answerability_route: String(message.telemetry?.answerability_route || ''),
          cited_sources_count: Number(message.telemetry?.cited_sources_count || 0),
        },
      });
    } catch {
      // Clipboard may be unavailable in restricted contexts.
    }
  };

  return (
    <>
      <div
        className={`app-light-surface chat-panel-surface bg-white shadow-md border border-oracle-border h-full flex flex-col overflow-hidden relative transition-all duration-300 ${
          !isInitialCentered && isGraphPanelOpen ? 'pr-[50%]' : ''
        }`}
      >
      {isInitialCentered ? (
        <div className="chat-start-surface flex-1 min-h-0 bg-oracle-bg-gray flex items-center justify-center px-6">
          <div className="w-full max-w-3xl flex flex-col items-center gap-6">
            <h2 className="text-4xl font-semibold text-oracle-dark-gray text-center">
              What are you working on?
            </h2>
            {renderComposer(promptPlaceholder)}
          </div>
        </div>
      ) : (
        <>
          <div
            className={`chat-conversation-header px-4 py-3 border-b border-oracle-border flex items-center gap-3 flex-shrink-0 bg-gray-50 ${
              isHeaderMenuOpen ? 'chat-conversation-header--menu-open' : ''
            }`}
          >
            <div className="w-9 h-9 rounded-xl bg-oracle-red flex items-center justify-center flex-shrink-0 overflow-hidden">
              {showAssistantAvatarImage ? (
                <img
                  src={assistantAvatarUrl}
                  alt={assistantDisplayName}
                  className="w-full h-full object-cover rounded-xl"
                  onError={() => setAssistantAvatarImageFailed(true)}
                />
              ) : (
                <span className="text-white text-sm font-bold">{assistantAvatarLetter}</span>
              )}
            </div>
            <div className="min-w-0">
              {isInlineRenaming && activeConversationId ? (
                <div className="flex items-center gap-2">
                  <input
                    ref={titleInputRef}
                    type="text"
                    value={renameDraft}
                    disabled={renamingConversation}
                    onChange={(event) => setRenameDraft(event.target.value)}
                    onBlur={() => {
                      if (skipBlurRenameRef.current) {
                        skipBlurRenameRef.current = false;
                        return;
                      }
                      void submitInlineRename();
                    }}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault();
                        void submitInlineRename();
                        return;
                      }
                      if (event.key === 'Escape') {
                        event.preventDefault();
                        cancelInlineRename();
                      }
                    }}
                    className="input-oracle h-8 py-1 text-sm font-semibold"
                    aria-label="Chat title"
                  />
                </div>
              ) : (
                <div className="font-semibold text-oracle-dark-gray text-sm truncate">
                  {activeConversationTitle || 'New chat'}
                </div>
              )}
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-oracle-light-gray">
                  {scopeSubtitle}
                </span>
              </div>
            </div>
            <div className="ml-auto relative" ref={headerMenuRef}>
              <button
                type="button"
                className="p-1.5 rounded-md text-oracle-medium-gray hover:bg-black/5 transition-colors"
                aria-label="Chat actions"
                aria-haspopup="menu"
                aria-expanded={isHeaderMenuOpen}
                title="Chat actions"
                onClick={() => setIsHeaderMenuOpen((prev) => !prev)}
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5.25a.75.75 0 110 1.5.75.75 0 010-1.5zm0 5.25a.75.75 0 110 1.5.75.75 0 010-1.5zm0 5.25a.75.75 0 110 1.5.75.75 0 010-1.5z" />
                </svg>
              </button>
              {isHeaderMenuOpen && (
                <div
                  className="chat-header-actions-menu absolute right-0 top-full mt-2 w-48 overflow-hidden rounded-lg border border-gray-200 bg-white py-2 shadow-xl z-50"
                  role="menu"
                  aria-label="Chat actions"
                >
                  <button
                    type="button"
                    role="menuitem"
                    className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-100 flex items-center gap-2 disabled:opacity-60"
                    onClick={startInlineRename}
                    disabled={!activeConversationId || renamingConversation || deletingConversation || isInlineRenaming}
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
                    {renamingConversation ? 'Renaming...' : 'Rename chat'}
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-100 flex items-center gap-2"
                    onClick={() => {
                      setIsGraphPanelOpen((prev) => {
                        const next = !prev;
                        if (next) {
                          resetGraphZoom();
                        }
                        return next;
                      });
                      setIsHeaderMenuOpen(false);
                    }}
                  >
                    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
                      <path d="M200,152a31.84,31.84,0,0,0-19.53,6.68l-23.11-18A31.65,31.65,0,0,0,160,128c0-.74,0-1.48-.08-2.21l13.23-4.41A32,32,0,1,0,168,104c0,.74,0,1.48.08,2.21l-13.23,4.41A32,32,0,0,0,128,96a32.59,32.59,0,0,0-5.27.44L115.89,81A32,32,0,1,0,96,88a32.59,32.59,0,0,0,5.27-.44l6.84,15.4a31.92,31.92,0,0,0-8.57,39.64L73.83,165.44a32.06,32.06,0,1,0,10.63,12l25.71-22.84a31.91,31.91,0,0,0,37.36-1.24l23.11,18A31.65,31.65,0,0,0,168,184a32,32,0,1,0,32-32Zm0-64a16,16,0,1,1-16,16A16,16,0,0,1,200,88ZM80,56A16,16,0,1,1,96,72,16,16,0,0,1,80,56ZM56,208a16,16,0,1,1,16-16A16,16,0,0,1,56,208Zm56-80a16,16,0,1,1,16,16A16,16,0,0,1,112,128Zm88,72a16,16,0,1,1,16-16A16,16,0,0,1,200,200Z" />
                    </svg>
                    {isGraphPanelOpen ? 'Hide graph' : 'Graph'}
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 flex items-center gap-2 disabled:opacity-60"
                    onClick={() => {
                      setIsDeleteConfirmOpen(true);
                      setIsHeaderMenuOpen(false);
                    }}
                    disabled={!activeConversationId || deletingConversation || renamingConversation}
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 7h12M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2m-7 0l1 12h6l1-12M10 11v6m4-6v6" />
                    </svg>
                    Delete chat
                  </button>
                </div>
              )}
            </div>
          </div>

          <RAGChatMessageList
            listRef={listRef}
            loadingConversation={loadingConversation}
            messages={messages}
            loading={loading}
            loadingElapsedSeconds={loadingElapsedSeconds}
            assistantDisplayName={assistantDisplayName}
            assistantAvatarUrl={assistantAvatarUrl}
            assistantAvatarLetter={assistantAvatarLetter}
            showAssistantAvatarImage={showAssistantAvatarImage}
            userInitials={userInitials}
            userFirstName={user?.name?.split(' ')[0] || 'You'}
            scopeOptions={scopeOptions}
            copiedMessageId={copiedMessageId}
            messageFeedback={messageFeedback}
            onAssistantAvatarImageError={() => setAssistantAvatarImageFailed(true)}
            onOpenSourcePreview={(source) => void handleOpenSourcePreview(source)}
            onCopyAssistantAnswer={handleCopyAssistantAnswer}
            onMessageFeedback={handleMessageFeedback}
          />
          <div className="chat-composer-footer p-3 border-t border-oracle-border flex-shrink-0 bg-white">
            {renderComposer(composerPlaceholder)}
          </div>
        </>
      )}
      {!isInitialCentered && isGraphPanelOpen && (
        <RAGChatGraphPanel
          graphThreadId={graphThreadId}
          graphDefinitionLoading={graphDefinitionQuery.isLoading}
          graphZoom={graphZoom}
          graphPanning={graphPanning}
          graphCanvasSize={graphCanvasSize}
          graphEffectiveViewBox={graphEffectiveViewBox}
          graphContainerRef={graphContainerRef}
          graphEdgePaths={graphEdgePaths}
          graphRenderNodes={graphRenderNodes}
          graphNodeStates={graphNodeStates}
          graphLatestMetrics={graphLatestMetrics}
          selectedGraphNodeKey={selectedGraphNodeKey}
          selectedGraphNodeStatus={selectedGraphNodeStatus}
          selectedGraphNodeState={selectedGraphNodeState}
          selectedGraphNodeDetail={selectedGraphNodeDetail}
          onClose={() => setIsGraphPanelOpen(false)}
          onZoomOut={() => adjustGraphZoom(-0.1)}
          onZoomIn={() => adjustGraphZoom(0.1)}
          onResetZoom={resetGraphZoom}
          onPanStart={handleGraphPanStart}
          onSelectNode={setSelectedGraphNodeKey}
          resolveEdgeClassName={resolveEdgeClassName}
          resolveNodeClassName={resolveNodeClassName}
          resolveGraphNodeStatus={resolveGraphNodeStatus}
          formatNodeDuration={formatNodeDuration}
          formatJsonForDisplay={formatJsonForDisplay}
        />
      )}
      </div>
      <RAGChatSourcePreviewModal
        open={isSourcePreviewOpen}
        title={sourcePreviewTitle}
        pageNumber={sourcePreviewPageNumber}
        imageUri={sourcePreviewImageUri}
        markdown={sourcePreviewMarkdown}
        evidenceSnippet={sourcePreviewEvidenceSnippet}
        loading={sourcePreviewLoading}
        imageError={sourcePreviewImageError}
        markdownError={sourcePreviewMarkdownError}
        onClose={() => setIsSourcePreviewOpen(false)}
        onCopyMarkdown={copySourcePreviewMarkdown}
      />
      {isDeleteConfirmOpen && (
        <ConfirmDeleteModal
          title="Delete chat"
          message="Are you sure you want to delete this chat?"
          detail="This action cannot be undone."
          loading={deletingConversation}
          onConfirm={() => void handleDeleteConversation()}
          onCancel={() => setIsDeleteConfirmOpen(false)}
        />
      )}
    </>
  );
}
