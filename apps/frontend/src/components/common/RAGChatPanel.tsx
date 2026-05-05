import {
  cloneElement,
  isValidElement,
  type ComponentPropsWithoutRef,
  type ReactElement,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import dagre from '@dagrejs/dagre';

import { useAuth } from '../../context/AuthContext';
import { useRAGChat } from '../../context/RAGChatContext';
import {
  normalizeArchiveSlugs,
  normalizeMetadataFields,
  parseChatSelectors,
  parseChatSelectorsDetailed,
  type ParsedChatSelectorToken,
  type ParsedChatSelectors,
} from '../../lib/chatSelectors';
import { queryKeys } from '../../lib/queryClient';
import {
  chatApi,
  ragApi,
  settingsApi,
  type ChatRequestOptions,
  type GraphDefinition,
  type GraphRuntimeEvent,
  type RAGScopeOptions,
  type ReasoningResult,
} from '../../services/api';
import { ConfirmDeleteModal } from './ConfirmDeleteModal';
import { GlassModal } from './GlassModal';
import { LoadingState } from './LoadingState';

function getInitials(name: string): string {
  return name
    .split(' ')
    .map((n) => n[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

type Source = {
  doc_id: string;
  name: string;
  source_number?: number;
  file_id?: number;
  page_number?: number;
  object_name_page?: string;
  snippet?: string;
};

type Message = {
  messageId: string;
  role: 'user' | 'assistant';
  text: string;
  timestamp: Date;
  localOnly?: boolean;
  modelUsed?: string;
  sources?: Source[];
  citedSources?: Source[];
  retrievedSources?: Source[];
  error?: string;
  reasoning?: ReasoningResult;
  telemetry?: Record<string, any>;
};

type FeedbackKind = 'up' | 'down';

type NodeRuntimeStatus = 'idle' | 'running' | 'completed' | 'failed';

type NodeRuntimeState = {
  status: NodeRuntimeStatus;
  startedAt?: string;
  endedAt?: string;
  durationMs?: number;
  lastEventType?: string;
  error?: string;
};

type GraphRenderNode = {
  key: string;
  label: string;
  kind: string;
  level: number;
  x: number;
  y: number;
  width: number;
};

type GraphEdgePath = {
  source: string;
  target: string;
  condition: string;
  points: Array<{ x: number; y: number }>;
};

const COMPOSER_TOKEN_PLACEHOLDER_BASE_SPACES = 2;
const COMPOSER_TOKEN_PLACEHOLDER_MIN_LENGTH = 10;
const COMPOSER_METADATA_TOKEN_PLACEHOLDER_MIN_LENGTH = 12;
const LOCAL_SELECTOR_HELP_LIST_LIMIT = 18;

const DEFAULT_GRAPH_DEFINITION: GraphDefinition = {
  nodes: [
    { key: 'classify_intent', label: 'Classify intent', kind: 'decision' },
    { key: 'search_response', label: 'Search response', kind: 'terminal_branch' },
    { key: 'resolve_scope', label: 'Resolve scope', kind: 'decision' },
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
    { source: 'resolve_scope', target: 'retrieve_candidates', condition: '' },
    { source: 'retrieve_candidates', target: 'fuse_page_evidence', condition: '' },
    { source: 'fuse_page_evidence', target: 'maybe_verify_visual', condition: '' },
    { source: 'maybe_verify_visual', target: 'synthesize_document_answer', condition: '' },
    { source: 'synthesize_document_answer', target: 'persist_turn', condition: '' },
    { source: 'persist_turn', target: 'END', condition: '' },
  ],
  start_node: 'classify_intent',
  end_node: 'persist_turn',
};

type ChatRequestBuildResult = {
  cleanedQuestion: string;
  selectors: ParsedChatSelectors;
  requestOptions: ChatRequestOptions;
  metadataRequestedExplicitly: boolean;
};

type ComposerSelectorState = {
  metadataMode: 'auto' | 'metadata_first';
  archiveSlugs: string[];
  metadataFields: string[];
  metadataRequestedExplicitly: boolean;
};

type SelectorSuggestion = {
  id: string;
  label: string;
  description?: string;
  replacement: string;
  group: 'special' | 'files' | 'metadata';
  kind: 'metadata' | 'file' | 'field';
};

type SelectorSuggestionGroup = {
  key: 'special' | 'files' | 'metadata';
  label: string;
  items: SelectorSuggestion[];
};

type UserMessageSelectorChipTone = 'metadata' | 'file' | 'field';

type UserMessageSelectorChip = {
  id: string;
  label: string;
  tone: UserMessageSelectorChipTone;
};

type UserMessagePresentation = {
  bodyText: string;
  selectorChips: UserMessageSelectorChip[];
  inlineParts: Array<
    | { id: string; type: 'text'; value: string }
    | { id: string; type: 'chip'; chip: UserMessageSelectorChip; token?: ParsedChatSelectorToken }
  >;
};

type ComposerInlinePart =
  | UserMessagePresentation['inlineParts'][number]
  | { id: string; type: 'caret' };

function buildChatRequestOptionsFromComposer(
  question: string,
  scopeOptions: RAGScopeOptions | null | undefined,
  composerSelectors: ComposerSelectorState
): ChatRequestBuildResult {
  const parsedSelectors = parseChatSelectors({ question, scopeOptions });
  const metadataRequestedExplicitly =
    composerSelectors.metadataRequestedExplicitly || /(^|[\s,;])@metadata\b/i.test(question);
  const archiveSlugs = normalizeArchiveSlugs([
    ...composerSelectors.archiveSlugs,
    ...parsedSelectors.archiveSlugs,
  ]);
  const metadataFields = normalizeMetadataFields([
    ...composerSelectors.metadataFields,
    ...parsedSelectors.metadataFields,
  ]);
  const metadataMode: 'auto' | 'metadata_first' =
    composerSelectors.metadataRequestedExplicitly ||
    composerSelectors.metadataMode === 'metadata_first' ||
    parsedSelectors.metadataMode === 'metadata_first' ||
    metadataFields.length > 0
      ? 'metadata_first'
      : 'auto';
  const perDocumentRequested = shouldUsePerDocumentSummary(question, archiveSlugs);
  return {
    cleanedQuestion: parsedSelectors.cleanedQuestion,
    selectors: {
      cleanedQuestion: parsedSelectors.cleanedQuestion,
      metadataMode,
      archiveSlugs,
      metadataFields,
    },
    metadataRequestedExplicitly,
    requestOptions: {
      summary_mode: perDocumentRequested ? 'per_document' : 'default',
      ...(perDocumentRequested
        ? {
            candidate_k: 60,
            min_pages_per_selected_doc: 1,
          }
        : {}),
      metadata_mode: metadataMode,
      archive_slugs: archiveSlugs,
      metadata_fields: metadataFields,
    },
  };
}

function buildEffectiveComposerQuestionText(requestBuild: ChatRequestBuildResult): string {
  const cleanedQuestion = requestBuild.cleanedQuestion.trim();
  if (cleanedQuestion.length >= 3) return cleanedQuestion;

  const archiveSlugs = requestBuild.selectors.archiveSlugs;
  const metadataFields = requestBuild.selectors.metadataFields;
  const metadataRequested = requestBuild.selectors.metadataMode === 'metadata_first';

  if (metadataFields.length > 0 && archiveSlugs.length > 0) {
    return `Metadata: ${metadataFields.slice(0, 2).join(', ')} en ${archiveSlugs.slice(0, 2).join(', ')}`;
  }
  if (metadataFields.length > 0) {
    return `Metadata: ${metadataFields.slice(0, 3).join(', ')}`;
  }
  if (metadataRequested && archiveSlugs.length > 0) {
    return `Metadata de ${archiveSlugs.slice(0, 3).join(', ')}`;
  }
  if (metadataRequested) {
    return 'Consulta de metadata';
  }
  if (archiveSlugs.length > 0) {
    return `Inventario de ${archiveSlugs.slice(0, 3).join(', ')}`;
  }
  return '';
}

function shouldUsePerDocumentSummary(question: string, archiveSlugs: string[]): boolean {
  if (!archiveSlugs.length) return false;
  const normalized = String(question || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase();
  return [
    'lista los nombres exactos',
    'pdf relevantes',
    'evidencia documental',
    'documentos integran',
    'integran el expediente',
    'documento base',
    'contrato base',
    'instrumento vigente',
    'de donde fue extraido',
    'dato clave',
    'datos clave',
    'representante',
    'representantes',
    'facultades para firmar',
    'clausulas equivalentes',
  ].some((term) => normalized.includes(term));
}

function getSelectorSearchContext(value: string, caret: number): { token: string; start: number; end: number } | null {
  const safeValue = String(value || '');
  const safeCaret = Math.max(0, Math.min(Number.isFinite(caret) ? caret : safeValue.length, safeValue.length));
  const uptoCaret = safeValue.slice(0, safeCaret);
  const match = uptoCaret.match(/(^|[\s,;])([@/][^\s,;]*)$/);
  if (!match) return null;
  const token = match[2] || '';
  if (!token) return null;
  return {
    token,
    start: safeCaret - token.length,
    end: safeCaret,
  };
}

function getSelectorSuggestionMatchRank(value: string, query: string): [number, number, number] {
  const normalizedValue = value.toLowerCase();
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return [0, 0, value.length];
  if (normalizedValue === normalizedQuery) return [0, 0, value.length];
  if (normalizedValue.startsWith(normalizedQuery)) return [1, 0, value.length];
  const wordBoundaryIndex = normalizedValue.indexOf(` ${normalizedQuery}`);
  if (wordBoundaryIndex >= 0) return [2, wordBoundaryIndex, value.length];
  const containsIndex = normalizedValue.indexOf(normalizedQuery);
  if (containsIndex >= 0) return [3, containsIndex, value.length];
  return [4, Number.MAX_SAFE_INTEGER, value.length];
}

function rankSelectorSuggestionValue(left: string, right: string, query: string): number {
  const leftRank = getSelectorSuggestionMatchRank(left, query);
  const rightRank = getSelectorSuggestionMatchRank(right, query);
  if (leftRank[0] !== rightRank[0]) return leftRank[0] - rightRank[0];
  if (leftRank[1] !== rightRank[1]) return leftRank[1] - rightRank[1];
  if (leftRank[2] !== rightRank[2]) return leftRank[2] - rightRank[2];
  return left.localeCompare(right);
}

function getSlashSelectorIntent(token: string): {
  showFiles: boolean;
  showMetadata: boolean;
  fileQuery: string;
  fieldQuery: string;
} {
  const normalizedToken = token.toLowerCase();
  if (normalizedToken === '/') {
    return { showFiles: true, showMetadata: true, fileQuery: '', fieldQuery: '' };
  }

  if (normalizedToken.startsWith('/file:')) {
    return {
      showFiles: true,
      showMetadata: false,
      fileQuery: token.slice(6).trim().toLowerCase(),
      fieldQuery: '',
    };
  }

  if (normalizedToken.startsWith('/col:')) {
    return {
      showFiles: false,
      showMetadata: true,
      fileQuery: '',
      fieldQuery: token.slice(5).trim().toLowerCase(),
    };
  }

  const query = token.slice(1).trim().toLowerCase();
  if (['f', 'fi', 'fil', 'file'].includes(query)) {
    return { showFiles: true, showMetadata: false, fileQuery: '', fieldQuery: '' };
  }
  if (['c', 'co', 'col'].includes(query)) {
    return { showFiles: false, showMetadata: true, fileQuery: '', fieldQuery: '' };
  }

  return {
    showFiles: Boolean(query),
    showMetadata: Boolean(query),
    fileQuery: query,
    fieldQuery: query,
  };
}

function buildSelectorSuggestionGroups(
  input: string,
  caret: number,
  scopeOptions: RAGScopeOptions | null | undefined,
  composerSelectors: ComposerSelectorState,
  composerTokens: ParsedChatSelectorToken[]
): { context: { token: string; start: number; end: number } | null; groups: SelectorSuggestionGroup[] } {
  const context = getSelectorSearchContext(input, caret);
  if (!context) {
    return { context: null, groups: [] };
  }

  const normalizedToken = context.token.toLowerCase();
  const normalizedFiles = Array.isArray(scopeOptions?.files) ? scopeOptions.files : [];
  const normalizedFields = Array.isArray(scopeOptions?.metadata_fields) ? scopeOptions.metadata_fields : [];
  const tokenizedArchiveSlugs = normalizeArchiveSlugs(
    composerTokens.filter((token) => token.kind === 'file').map((token) => token.label)
  );
  const tokenizedMetadataFields = normalizeMetadataFields(
    composerTokens.filter((token) => token.kind === 'field').map((token) => token.label)
  );
  const groups: SelectorSuggestionGroup[] = [];

  if (normalizedToken.startsWith('@')) {
    if ('@metadata'.startsWith(normalizedToken) && !composerSelectors.metadataRequestedExplicitly) {
      groups.push({
        key: 'special',
        label: 'Metadata',
        items: [
          {
            id: 'metadata-mode',
            label: '@metadata',
            description: 'Run metadata first and deepen into documents if needed.',
            replacement: '@metadata ',
            group: 'special',
            kind: 'metadata',
          },
        ],
      });
    }
    return { context, groups };
  }

  if (!normalizedToken.startsWith('/')) {
    return { context, groups: [] };
  }

  const { showFiles, showMetadata, fileQuery, fieldQuery } = getSlashSelectorIntent(context.token);

  if (showFiles) {
    const items = normalizedFiles
      .filter((value) => !tokenizedArchiveSlugs.includes(value))
      .filter((value) => !fileQuery || value.toLowerCase().includes(fileQuery))
      .sort((left, right) => rankSelectorSuggestionValue(left, right, fileQuery))
      .slice(0, 12)
      .map<SelectorSuggestion>((value) => ({
        id: `file-${value}`,
        label: value,
        replacement: `/file:${value} `,
        group: 'files',
        kind: 'file',
      }));
    if (items.length > 0) {
      groups.push({ key: 'files', label: 'Files', items });
    }
  }

  if (showMetadata) {
    const items = normalizedFields
      .filter((value) => !tokenizedMetadataFields.includes(value))
      .filter((value) => !fieldQuery || value.toLowerCase().includes(fieldQuery))
      .map<SelectorSuggestion>((value) => ({
        id: `field-${value}`,
        label: value,
        replacement: `/col:${value} `,
        group: 'metadata',
        kind: 'field',
      }));
    if (items.length > 0) {
      groups.push({ key: 'metadata', label: 'Metadata', items });
    }
  }

  return { context, groups };
}

function buildSelectorStateFromTelemetry(telemetry?: Record<string, any>): ComposerSelectorState {
  const requestedArchiveSlugs = Array.isArray(telemetry?.requested_archive_slugs)
    ? telemetry.requested_archive_slugs
    : [];
  const requestedMetadataFields = Array.isArray(telemetry?.requested_metadata_fields)
    ? telemetry.requested_metadata_fields
    : [];
  const requestedMetadataMode =
    String(telemetry?.metadata_mode || '').trim().toLowerCase() === 'metadata_first';
  return {
    metadataMode:
      requestedMetadataMode || requestedMetadataFields.length > 0 ? 'metadata_first' : 'auto',
    archiveSlugs: normalizeArchiveSlugs(requestedArchiveSlugs),
    metadataFields: normalizeMetadataFields(requestedMetadataFields),
    metadataRequestedExplicitly: Boolean(telemetry?.metadata_requested_explicitly),
  };
}

function removeComposerToken(value: string, start: number, end: number): { nextValue: string; nextCaret: number } {
  const before = value.slice(0, start);
  const after = value.slice(end);
  const needsSpace = Boolean(before && after && !/\s$/.test(before) && !/^\s/.test(after));
  const nextValue = `${before}${needsSpace ? ' ' : ''}${after}`.replace(/\s{2,}/g, ' ').trimStart();
  const nextCaret = Math.min(start, nextValue.length);
  return { nextValue, nextCaret };
}

function replaceComposerToken(
  value: string,
  start: number,
  end: number,
  replacement: string
): { nextValue: string; nextCaret: number } {
  const nextValue = `${value.slice(0, start)}${replacement}${value.slice(end)}`;
  const nextCaret = start + replacement.length;
  return {
    nextValue,
    nextCaret,
  };
}

function serializeComposerInput(value: string, tokens: ParsedChatSelectorToken[]): string {
  if (tokens.length === 0) return value;
  const ordered = tokens.slice().sort((left, right) => left.start - right.start);
  let cursor = 0;
  let serialized = '';

  for (const token of ordered) {
    serialized += value.slice(cursor, token.start);
    serialized += token.raw;
    cursor = token.end;
  }

  serialized += value.slice(cursor);
  return serialized;
}

function reconcileComposerTokens(
  previousValue: string,
  nextValue: string,
  tokens: ParsedChatSelectorToken[]
): ParsedChatSelectorToken[] {
  if (tokens.length === 0 || previousValue === nextValue) return tokens;

  let prefixLength = 0;
  while (
    prefixLength < previousValue.length &&
    prefixLength < nextValue.length &&
    previousValue[prefixLength] === nextValue[prefixLength]
  ) {
    prefixLength += 1;
  }

  let previousSuffix = previousValue.length;
  let nextSuffix = nextValue.length;
  while (
    previousSuffix > prefixLength &&
    nextSuffix > prefixLength &&
    previousValue[previousSuffix - 1] === nextValue[nextSuffix - 1]
  ) {
    previousSuffix -= 1;
    nextSuffix -= 1;
  }

  const delta = (nextSuffix - prefixLength) - (previousSuffix - prefixLength);

  return tokens
    .flatMap((token) => {
      if (token.end <= prefixLength) {
        return [token];
      }
      if (token.start >= previousSuffix) {
        return [
          {
            ...token,
            start: token.start + delta,
            end: token.end + delta,
          },
        ];
      }
      return [];
    })
    .sort((left, right) => left.start - right.start);
}

function buildComposerTokenPayload(suggestion: SelectorSuggestion): Pick<ParsedChatSelectorToken, 'kind' | 'label' | 'raw'> {
  if (suggestion.kind === 'metadata') {
    return {
      kind: 'metadata',
      label: 'Metadata',
      raw: '@metadata',
    };
  }
  if (suggestion.kind === 'file') {
    return {
      kind: 'file',
      label: suggestion.label,
      raw: `/file:${suggestion.label}`,
    };
  }
  return {
    kind: 'field',
    label: suggestion.label,
    raw: `/col:${suggestion.label}`,
  };
}

function insertComposerTokenLabel(
  value: string,
  start: number,
  end: number,
  label: string,
  kind: SelectorSuggestion['kind']
): { nextValue: string; tokenStart: number; tokenEnd: number; nextCaret: number } {
  const before = value.slice(0, start);
  const after = value.slice(end);
  const needsTrailingSpace = after.length === 0 || !/^[\s,.;:!?)]/.test(after);
  const minPlaceholderLength =
    kind === 'metadata'
      ? COMPOSER_METADATA_TOKEN_PLACEHOLDER_MIN_LENGTH
      : COMPOSER_TOKEN_PLACEHOLDER_MIN_LENGTH;
  const placeholderSpaces = ' '.repeat(
    Math.max(COMPOSER_TOKEN_PLACEHOLDER_BASE_SPACES, minPlaceholderLength - label.length)
  );
  const placeholderLabel = `${label}${placeholderSpaces}`;
  const visibleReplacement = `${placeholderLabel}${needsTrailingSpace ? ' ' : ''}`;
  const { nextValue, nextCaret } = replaceComposerToken(value, start, end, visibleReplacement);
  return {
    nextValue,
    tokenStart: before.length,
    tokenEnd: before.length + placeholderLabel.length,
    nextCaret,
  };
}

function buildSelectorChips(selectorState: ComposerSelectorState): UserMessageSelectorChip[] {
  const selectorChips: UserMessageSelectorChip[] = [];

  if (selectorState.metadataRequestedExplicitly) {
    selectorChips.push({
      id: 'metadata-mode',
      label: 'Metadata',
      tone: 'metadata',
    });
  }

  for (const archiveSlug of selectorState.archiveSlugs) {
    selectorChips.push({
      id: `file-${archiveSlug}`,
      label: archiveSlug,
      tone: 'file',
    });
  }

  for (const metadataField of selectorState.metadataFields) {
    selectorChips.push({
      id: `field-${metadataField}`,
      label: metadataField,
      tone: 'field',
    });
  }

  return selectorChips;
}

function buildSelectorChipFromToken(token: ParsedChatSelectorToken): UserMessageSelectorChip {
  if (token.kind === 'metadata') {
    return {
      id: 'metadata-mode',
      label: 'Metadata',
      tone: 'metadata',
    };
  }
  if (token.kind === 'file') {
    return {
      id: `file-${token.label}`,
      label: token.label,
      tone: 'file',
    };
  }
  return {
    id: `field-${token.label}`,
    label: token.label,
    tone: 'field',
  };
}

function buildInlineSelectorParts(
  text: string,
  tokens: ParsedChatSelectorToken[]
): UserMessagePresentation['inlineParts'] {
  if (!tokens.length) {
    return text
      ? [
          {
            id: 'text-0',
            type: 'text',
            value: text,
          },
        ]
      : [];
  }

  const parts: UserMessagePresentation['inlineParts'] = [];
  let cursor = 0;

  tokens
    .slice()
    .sort((left, right) => left.start - right.start)
    .forEach((token, index) => {
      if (token.start > cursor) {
        parts.push({
          id: `text-${cursor}-${index}`,
          type: 'text',
          value: text.slice(cursor, token.start),
        });
      }

      parts.push({
        id: `chip-${token.kind}-${token.start}-${index}`,
        type: 'chip',
        chip: buildSelectorChipFromToken(token),
        token,
      });
      cursor = token.end;
    });

  if (cursor < text.length) {
    parts.push({
      id: `text-${cursor}-tail`,
      type: 'text',
      value: text.slice(cursor),
    });
  }

  return parts;
}

function buildComposerVisualInlineParts(
  text: string,
  tokens: ParsedChatSelectorToken[],
  caret: number,
  showCaret: boolean
): ComposerInlinePart[] {
  const parts: ComposerInlinePart[] = [];
  const orderedTokens = tokens.slice().sort((left, right) => left.start - right.start);
  const safeCaret = Math.max(0, Math.min(caret, text.length));
  let cursor = 0;
  let caretInserted = false;

  const pushCaret = (id: string) => {
    if (!showCaret || caretInserted) return;
    parts.push({ id, type: 'caret' });
    caretInserted = true;
  };

  const pushText = (start: number, end: number, idSuffix: string) => {
    if (start > end) return;
    if (!showCaret || caretInserted || safeCaret < start || safeCaret > end) {
      if (start < end) {
        parts.push({
          id: `text-${start}-${idSuffix}`,
          type: 'text',
          value: text.slice(start, end),
        });
      }
      return;
    }

    if (start < safeCaret) {
      parts.push({
        id: `text-${start}-${idSuffix}-before-caret`,
        type: 'text',
        value: text.slice(start, safeCaret),
      });
    }

    pushCaret(`caret-${safeCaret}-${idSuffix}`);

    if (safeCaret < end) {
      parts.push({
        id: `text-${safeCaret}-${idSuffix}-after-caret`,
        type: 'text',
        value: text.slice(safeCaret, end),
      });
    }
  };

  orderedTokens.forEach((token, index) => {
    if (token.end <= cursor) return;
    const tokenStart = Math.max(cursor, Math.min(token.start, text.length));
    const tokenEnd = Math.max(tokenStart, Math.min(token.end, text.length));

    if (cursor < tokenStart) {
      pushText(cursor, tokenStart, `${index}`);
    }

    if (showCaret && !caretInserted && safeCaret <= tokenStart) {
      pushCaret(`caret-${safeCaret}-before-chip-${index}`);
    }

    parts.push({
      id: `chip-${token.kind}-${token.start}-${index}`,
      type: 'chip',
      chip: buildSelectorChipFromToken(token),
      token,
    });

    if (showCaret && !caretInserted && safeCaret > tokenStart && safeCaret <= tokenEnd) {
      pushCaret(`caret-${safeCaret}-after-chip-${index}`);
    }

    cursor = tokenEnd;
  });

  if (cursor < text.length || (showCaret && !caretInserted && safeCaret === text.length)) {
    pushText(cursor, text.length, 'tail');
  }

  if (showCaret && !caretInserted) {
    pushCaret(`caret-${safeCaret}-end`);
  }

  return parts;
}

function buildUserMessagePresentation(
  text: string,
  scopeOptions: RAGScopeOptions | null | undefined,
  telemetry?: Record<string, any>
): UserMessagePresentation {
  const rawText = String(text || '').trim();
  const parsed = parseChatSelectorsDetailed({ question: rawText, scopeOptions });
  const telemetrySelectors = buildSelectorStateFromTelemetry(telemetry);
  const metadataRequestedExplicitly =
    /(^|[\s,;])@metadata\b/i.test(rawText) || telemetrySelectors.metadataRequestedExplicitly;
  const selectorChips = buildSelectorChips({
    metadataMode:
      metadataRequestedExplicitly ||
      parsed.metadataFields.length > 0 ||
      telemetrySelectors.metadataFields.length > 0
        ? 'metadata_first'
        : 'auto',
    archiveSlugs: normalizeArchiveSlugs([
      ...parsed.archiveSlugs,
      ...telemetrySelectors.archiveSlugs,
    ]),
    metadataFields: normalizeMetadataFields([
      ...parsed.metadataFields,
      ...telemetrySelectors.metadataFields,
    ]),
    metadataRequestedExplicitly,
  });

  for (const archiveSlug of [] as string[]) {
    selectorChips.push({
      id: `file-${archiveSlug}`,
      label: `Archivo · ${archiveSlug}`,
      tone: 'file',
    });
  }

  for (const metadataField of [] as string[]) {
    selectorChips.push({
      id: `field-${metadataField}`,
      label: `Columna · ${metadataField}`,
      tone: 'field',
    });
  }

  return {
    bodyText: parsed.cleanedQuestion.trim() || rawText,
    selectorChips,
    inlineParts: buildInlineSelectorParts(rawText, parsed.tokens),
  };
}

function getUserMessageChipClassName(_tone: UserMessageSelectorChipTone): string {
  return 'border-white/15 bg-white/10 text-white/95';
}

function getComposerChipClassName(_tone: UserMessageSelectorChipTone): string {
  return 'composer-token-chip border-gray-200 bg-white text-oracle-dark-gray';
}

function getInlineChipClassName(baseClassName: string): string {
  return `inline-flex h-4 max-w-[18rem] items-center gap-0.5 whitespace-nowrap rounded-full border px-1.5 py-0 text-[10px] font-medium leading-none sm:max-w-[22rem] ${baseClassName}`;
}

function SelectorChipIcon({ tone }: { tone: UserMessageSelectorChipTone }) {
  switch (tone) {
    case 'metadata':
      return (
        <svg
          aria-hidden="true"
          className="h-3 w-3 shrink-0"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M2.5 4.5h11" />
          <path d="M4.5 8h7" />
          <path d="M6 11.5h4" />
        </svg>
      );
    case 'file':
      return (
        <svg
          aria-hidden="true"
          className="h-3 w-3 shrink-0"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M5 2.5h4l2.5 2.5v7.5a1 1 0 0 1-1 1h-5a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1Z" />
          <path d="M9 2.5v2.5h2.5" />
        </svg>
      );
    case 'field':
      return (
        <svg
          aria-hidden="true"
          className="h-3 w-3 shrink-0"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M2.5 3.5h11v9h-11z" />
          <path d="M7.75 3.5v9" />
        </svg>
      );
    default:
      return null;
  }
}

function stripInlineSourcesSection(value: string): string {
  const text = String(value || '').trim();
  if (!text) return '';
  const cleanedLines = text
    .split('\n')
    .filter((line) => {
      const trimmed = line.trim();
      if (!trimmed) return true;
      if (/^\**\s*(sources?|fuentes?|citations?)\s*:?\**\s*$/i.test(trimmed)) return false;
      if (/^[-*]\s*\**\s*(source|fuente)\b/i.test(trimmed)) return false;
      return true;
    });
  return stripInlineCitationMarkers(cleanedLines.join('\n'))
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function stripInlineCitationMarkers(value: string): string {
  return String(value || '')
    .replace(/(^|[\s(])\[(?:\d{1,3})(?:\s*,\s*\d{1,3})*\](?=([\s).,;:]|$))/g, '$1')
    .replace(/[ \t]+([.,;:])/g, '$1');
}

const MARKDOWN_TABLE_PATTERN = /(^|\n)\|.+\|\n\|(?:\s*:?-+:?\s*\|)+/m;

function messageContainsMarkdownTable(value: string): boolean {
  return MARKDOWN_TABLE_PATTERN.test(String(value || ''));
}

function ChatMarkdownTable({ children }: ComponentPropsWithoutRef<'table'>) {
  return (
    <div className="not-prose my-3 max-w-full overflow-x-auto rounded-xl border border-gray-200 bg-white shadow-sm">
      <table className="min-w-[760px] w-full table-auto border-collapse text-left text-xs [&_td:nth-child(1)]:min-w-[10rem] [&_td:nth-child(2)]:min-w-[18rem] [&_td:nth-child(3)]:min-w-[7rem] [&_td:nth-child(4)]:min-w-[18rem] [&_th:nth-child(1)]:min-w-[10rem] [&_th:nth-child(2)]:min-w-[18rem] [&_th:nth-child(3)]:min-w-[7rem] [&_th:nth-child(4)]:min-w-[18rem]">
        {children}
      </table>
    </div>
  );
}

function ChatMarkdownThead({ children }: ComponentPropsWithoutRef<'thead'>) {
  return <thead className="bg-gray-50">{children}</thead>;
}

function ChatMarkdownTh({ children }: ComponentPropsWithoutRef<'th'>) {
  return (
    <th className="border-b border-gray-200 px-4 py-3 align-top text-left text-[11px] font-semibold uppercase tracking-wide text-oracle-dark-gray whitespace-nowrap">
      {children}
    </th>
  );
}

function ChatMarkdownTd({ children }: ComponentPropsWithoutRef<'td'>) {
  return (
    <td className="border-t border-gray-100 px-4 py-3 align-top leading-5 whitespace-normal break-words text-oracle-medium-gray">
      {children}
    </td>
  );
}

function ChatMarkdownH2({ children }: ComponentPropsWithoutRef<'h2'>) {
  return (
    <h2 className="mt-3 border-b border-gray-200 pb-1 text-[15px] font-semibold leading-6 text-oracle-dark-gray first:mt-0">
      {children}
    </h2>
  );
}

function ChatMarkdownH3({ children }: ComponentPropsWithoutRef<'h3'>) {
  return <h3 className="mt-2 text-sm font-semibold leading-5 text-oracle-dark-gray">{children}</h3>;
}

function ChatMarkdownP({ children }: ComponentPropsWithoutRef<'p'>) {
  return <p className="my-1.5 leading-6 text-oracle-dark-gray">{children}</p>;
}

function ChatMarkdownUl({ children }: ComponentPropsWithoutRef<'ul'>) {
  return <ul className="my-2 space-y-1.5 pl-5 leading-6 marker:text-oracle-red">{children}</ul>;
}

function ChatMarkdownOl({ children }: ComponentPropsWithoutRef<'ol'>) {
  return <ol className="my-2 space-y-2 pl-5 leading-6 marker:font-semibold marker:text-oracle-red">{children}</ol>;
}

function ChatMarkdownLi({ children }: ComponentPropsWithoutRef<'li'>) {
  return <li className="pl-1 leading-6 text-oracle-dark-gray">{children}</li>;
}

function ChatMarkdownStrong({ children }: ComponentPropsWithoutRef<'strong'>) {
  return <strong className="font-semibold text-oracle-dark-gray">{children}</strong>;
}

function ChatMarkdownCode({ children }: ComponentPropsWithoutRef<'code'>) {
  return (
    <code className="rounded border border-gray-200 bg-gray-50 px-1 py-0.5 text-[0.82em] text-oracle-dark-gray">
      {children}
    </code>
  );
}

const CHAT_MARKDOWN_COMPONENTS = {
  h2: ChatMarkdownH2,
  h3: ChatMarkdownH3,
  p: ChatMarkdownP,
  ul: ChatMarkdownUl,
  ol: ChatMarkdownOl,
  li: ChatMarkdownLi,
  strong: ChatMarkdownStrong,
  code: ChatMarkdownCode,
  table: ChatMarkdownTable,
  thead: ChatMarkdownThead,
  th: ChatMarkdownTh,
  td: ChatMarkdownTd,
};

const SOURCE_HIGHLIGHT_STOPWORDS = new Set([
  'ante',
  'aqui',
  'cada',
  'como',
  'con',
  'cual',
  'cuales',
  'cuando',
  'del',
  'desde',
  'donde',
  'esta',
  'este',
  'esto',
  'estos',
  'para',
  'pero',
  'porque',
  'segun',
  'sobre',
  'tambien',
  'the',
  'that',
  'this',
  'with',
]);

function extractDocumentPageMarkdown(markdown: string, pageNumber: number): string {
  const content = String(markdown || '');
  const normalizedPage = Math.max(1, Math.floor(Number(pageNumber) || 1));
  const headingRegex = /^##\s+Page\s+(\d+)\s*$/gim;
  const matches = Array.from(content.matchAll(headingRegex));
  if (matches.length === 0) return content.trim();

  for (let index = 0; index < matches.length; index += 1) {
    const current = matches[index];
    const next = matches[index + 1];
    const currentPage = Number(current[1]);
    if (currentPage !== normalizedPage || current.index === undefined) continue;
    const sectionStart = current.index + current[0].length;
    const sectionEnd = next?.index ?? content.length;
    return content.slice(sectionStart, sectionEnd).trim();
  }
  return '';
}

function buildSourceHighlightTerms(snippet: string): string[] {
  const text = String(snippet || '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!text) return [];

  const seen = new Set<string>();
  const terms: string[] = [];
  const words = text.match(/[\p{L}\p{N}]{4,}/gu) || [];
  for (const word of words) {
    const normalized = word.toLocaleLowerCase();
    if (SOURCE_HIGHLIGHT_STOPWORDS.has(normalized) || /^\d+$/.test(normalized) || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    terms.push(word);
    if (terms.length >= 18) break;
  }
  return terms.sort((left, right) => right.length - left.length);
}

function escapeRegExp(value: string): string {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function highlightText(value: string, highlightTerms: string[]): ReactNode {
  if (!highlightTerms.length) return value;
  const pattern = highlightTerms.map(escapeRegExp).filter(Boolean).join('|');
  if (!pattern) return value;
  const regex = new RegExp(`(${pattern})`, 'gi');
  const parts = String(value).split(regex);
  return parts.map((part, index) => {
    if (!part) return null;
    const isMatch = highlightTerms.some((term) => term.toLocaleLowerCase() === part.toLocaleLowerCase());
    if (!isMatch) return part;
    return (
      <mark
        key={`${part}-${index}`}
        className="rounded bg-yellow-200 px-0.5 text-oracle-dark-gray ring-1 ring-yellow-300"
      >
        {part}
      </mark>
    );
  });
}

function highlightInlineChildren(children: ReactNode, highlightTerms: string[]): ReactNode {
  if (!highlightTerms.length) return children;
  if (typeof children === 'string' || typeof children === 'number') {
    return highlightText(String(children), highlightTerms);
  }
  if (Array.isArray(children)) {
    return children.map((child, index) => (
      <span key={index}>{highlightInlineChildren(child, highlightTerms)}</span>
    ));
  }
  if (isValidElement(children)) {
    const element = children as ReactElement<{ children?: ReactNode }>;
    return cloneElement(element, undefined, highlightInlineChildren(element.props.children, highlightTerms));
  }
  return children;
}

function buildSourcePreviewMarkdownComponents(highlightTerms: string[]) {
  const highlight = (children: ReactNode) => highlightInlineChildren(children, highlightTerms);
  return {
    h2: ({ children }: ComponentPropsWithoutRef<'h2'>) => (
      <h2 className="mt-3 border-b border-gray-200 pb-1 text-base font-semibold leading-6 text-oracle-dark-gray first:mt-0">
        {highlight(children)}
      </h2>
    ),
    h3: ({ children }: ComponentPropsWithoutRef<'h3'>) => (
      <h3 className="mt-2 text-sm font-semibold leading-5 text-oracle-dark-gray">{highlight(children)}</h3>
    ),
    p: ({ children }: ComponentPropsWithoutRef<'p'>) => (
      <p className="my-1.5 text-[13px] leading-6 text-oracle-dark-gray">{highlight(children)}</p>
    ),
    ul: ({ children }: ComponentPropsWithoutRef<'ul'>) => (
      <ul className="my-2 space-y-1.5 pl-5 leading-6 marker:text-oracle-red">{children}</ul>
    ),
    ol: ({ children }: ComponentPropsWithoutRef<'ol'>) => (
      <ol className="my-2 space-y-2 pl-5 leading-6 marker:font-semibold marker:text-oracle-red">{children}</ol>
    ),
    li: ({ children }: ComponentPropsWithoutRef<'li'>) => (
      <li className="pl-1 leading-6 text-oracle-dark-gray">{highlight(children)}</li>
    ),
    strong: ({ children }: ComponentPropsWithoutRef<'strong'>) => (
      <strong className="font-semibold text-oracle-dark-gray">{highlight(children)}</strong>
    ),
    code: ({ children }: ComponentPropsWithoutRef<'code'>) => (
      <code className="rounded border border-gray-200 bg-gray-50 px-1 py-0.5 text-[0.82em] text-oracle-dark-gray">
        {highlight(children)}
      </code>
    ),
    table: ChatMarkdownTable,
    thead: ChatMarkdownThead,
    th: ({ children }: ComponentPropsWithoutRef<'th'>) => (
      <th className="border-b border-gray-200 px-4 py-3 align-top text-left text-[11px] font-semibold uppercase tracking-wide text-oracle-dark-gray whitespace-nowrap">
        {highlight(children)}
      </th>
    ),
    td: ({ children }: ComponentPropsWithoutRef<'td'>) => (
      <td className="border-t border-gray-100 px-4 py-3 align-top leading-5 whitespace-normal break-words text-oracle-medium-gray">
        {highlight(children)}
      </td>
    ),
  };
}

function buildMessageMergeSignature(message: Message): string {
  const normalizedText = String(message.text || '').trim().replace(/\s+/g, ' ');
  return `${message.role}::${normalizedText}`;
}

function mergeLoadedConversationMessages(loaded: Message[], optimistic: Message[]): Message[] {
  if (optimistic.length === 0) {
    return loaded;
  }

  const loadedSignatures = new Set(loaded.map(buildMessageMergeSignature));
  const missingOptimisticMessages = optimistic.filter((message) => {
    if (!String(message.messageId || '').startsWith('local-')) {
      return false;
    }
    return !loadedSignatures.has(buildMessageMergeSignature(message));
  });

  if (missingOptimisticMessages.length === 0) {
    return loaded;
  }

  return [...loaded, ...missingOptimisticMessages].sort(
    (left, right) => left.timestamp.getTime() - right.timestamp.getTime()
  );
}

function formatJsonForDisplay(value: unknown): string {
  if (value === undefined) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function extractNodeResponseText(value: unknown): string {
  if (!value || typeof value !== 'object') return '';
  const obj = value as Record<string, any>;
  const candidates = [
    obj.answer_text,
    obj.response_text,
    obj.answer?.answer_text,
    obj.answer?.text,
    obj.result?.answer_text,
    obj.result?.answer?.answer_text,
    obj.final_response?.answer,
    obj.final_response?.answer_text,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim()) {
      return candidate.trim();
    }
  }
  return '';
}

const NODE_HEIGHT = 48;
const NODE_WIDTH_MIN = 100;
const NODE_WIDTH_MAX = 260;
const CHAR_WIDTH_APPROX = 8;
const NODE_PADDING_X = 24;

function computeNodeWidth(label: string, key: string): number {
  const maxLen = Math.max(label.length, key.length);
  const contentWidth = maxLen * CHAR_WIDTH_APPROX;
  const total = NODE_PADDING_X * 2 + contentWidth;
  return Math.max(NODE_WIDTH_MIN, Math.min(NODE_WIDTH_MAX, total));
}

function buildGraphWithDagre(
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

function mapSourcesFromArray(sourceItems: Array<Record<string, any>>): Source[] {
  return sourceItems.map((item: Record<string, any>, index: number) => {
    const sourceNumber = Number(item?.source_number ?? 0);
    const pageNumber = Number(item?.page_number ?? 0);
    const fileName = String(item?.file_name || item?.name || 'document').trim();
    const snippet = String(item?.snippet || '').trim();
    return {
      doc_id: String(sourceNumber || index + 1),
      name: `${fileName} - page ${pageNumber || '?'}`,
      source_number: sourceNumber || undefined,
      file_id: Number(item?.file_id ?? 0) || undefined,
      page_number: pageNumber || undefined,
      object_name_page: String(item?.object_name_page ?? ''),
      snippet: snippet || undefined,
    };
  });
}

function mapSourcesByMetadataKey(metadata: Record<string, any>, key: string): Source[] {
  const sourceItems = Array.isArray(metadata?.[key]) ? (metadata[key] as Array<Record<string, any>>) : [];
  if (sourceItems.length === 0) return [];
  return mapSourcesFromArray(sourceItems);
}

function mapCitedSourcesFromMetadata(metadata: Record<string, any>, fallbackSources: Source[]): Source[] {
  const explicitCitedSources = mapSourcesByMetadataKey(metadata, 'cited_sources');
  if (explicitCitedSources.length > 0) return explicitCitedSources;

  const selectedCitationNumbers = Array.isArray(metadata?.selected_citations)
    ? new Set(
        metadata.selected_citations
          .map((value: unknown) => Number(value))
          .filter((value: number) => Number.isFinite(value) && value > 0)
      )
    : new Set<number>();
  if (selectedCitationNumbers.size === 0) return [];
  return fallbackSources.filter((source) => {
    const sourceNumber = Number(source.source_number ?? source.doc_id ?? 0);
    return Number.isFinite(sourceNumber) && selectedCitationNumbers.has(sourceNumber);
  });
}

function mapSourcesFromMetadata(metadata: Record<string, any>): Source[] {
  const serializedSources = (
    Array.isArray(metadata?.sources)
      ? (metadata.sources as Array<Record<string, any>>)
      : Array.isArray(metadata?.cited_sources)
      ? (metadata.cited_sources as Array<Record<string, any>>)
      : Array.isArray(metadata?.retrieved_sources)
      ? (metadata.retrieved_sources as Array<Record<string, any>>)
      : []
  );
  if (serializedSources.length > 0) {
    return mapSourcesFromArray(serializedSources);
  }

  const analyzedPages = Array.isArray(metadata?.analyzed_pages) ? metadata.analyzed_pages : [];
  if (analyzedPages.length === 0) return [];
  const scopeFileId = Number(metadata?.scope_file_id ?? 0) || undefined;
  return analyzedPages.map((page: number, index: number) => {
    const pageNumber = Number(page);
    const normalizedPage = Number.isFinite(pageNumber) && pageNumber > 0 ? pageNumber : undefined;
    return {
      doc_id: String(index + 1),
      name: `page ${normalizedPage ?? "?"}`,
      source_number: index + 1,
      file_id: scopeFileId,
      page_number: normalizedPage,
      object_name_page: "",
    };
  });
}

function mapReasoningFromMetadata(metadata: Record<string, any>): ReasoningResult | undefined {
  const strategy = String(metadata?.strategy || '').trim();
  const answerMode = String(metadata?.answer_mode || '').trim();
  const visualConfirmationUsed = Boolean(metadata?.visual_confirmation_used);
  const analyzedPages = Array.isArray(metadata?.analyzed_pages)
    ? metadata.analyzed_pages
        .map((value: unknown) => Number(value))
        .filter((value: number) => !Number.isNaN(value))
    : [];
  const confidenceNotes = Array.isArray(metadata?.confidence_notes)
    ? metadata.confidence_notes
        .map((value: unknown) => String(value || '').trim())
        .filter((value: string) => Boolean(value))
    : [];
  if (!strategy && !answerMode && !visualConfirmationUsed && analyzedPages.length === 0 && confidenceNotes.length === 0) {
    return undefined;
  }
  return {
    strategy,
    answer_mode: answerMode,
    visual_confirmation_used: visualConfirmationUsed,
    analyzed_pages: analyzedPages,
    confidence_notes: confidenceNotes,
  };
}

function formatInferredScopeLabel(telemetry?: Record<string, any>): string {
  if (!telemetry || typeof telemetry !== 'object') return '';
  const origin = String(telemetry.scope_origin || '').trim().toLowerCase();
  if (origin !== 'inferred') return '';
  const codes = Array.isArray(telemetry.scope_document_codes)
    ? telemetry.scope_document_codes
        .map((value: unknown) => String(value || '').trim())
        .filter((value: string) => Boolean(value))
    : [];
  if (codes.length === 0) return '';
  const scopeCount = Number(telemetry.resolved_scope_file_count ?? 0) || 0;
  const suffix = scopeCount > 0 ? ` (${scopeCount} docs)` : '';
  return `Scope inferred: ${codes.join(', ')}${suffix}`;
}

type LocalComposerCommandKind = 'files' | 'metadata';

function resolveLocalComposerCommand(value: string): LocalComposerCommandKind | null {
  const normalized = String(value || '').trim().toLowerCase();
  if (['/', '/f', '/fi', '/fil', '/file', '/files'].includes(normalized)) {
    return 'files';
  }
  if (['@', '@m', '@me', '@met', '@meta', '@metad', '@metada', '@metadat', '@metadata'].includes(normalized)) {
    return 'metadata';
  }
  if (['/c', '/co', '/col', '/cols', '/field', '/fields'].includes(normalized)) {
    return 'metadata';
  }
  return null;
}

function formatLocalSelectorHelpList(values: string[], emptyMessage: string): string {
  const normalizedValues = values
    .map((value) => String(value || '').trim())
    .filter((value) => Boolean(value));
  if (normalizedValues.length === 0) {
    return emptyMessage;
  }
  const visibleValues = normalizedValues.slice(0, LOCAL_SELECTOR_HELP_LIST_LIMIT);
  const lines = visibleValues.map((value) => `- \`${value}\``);
  if (normalizedValues.length > visibleValues.length) {
    lines.push(`- ... and ${normalizedValues.length - visibleValues.length} more`);
  }
  return lines.join('\n');
}

function buildLocalComposerCommandMessages(
  rawInput: string,
  scopeOptions: RAGScopeOptions | null | undefined
): { userText: string; assistantText: string } | null {
  const userText = String(rawInput || '').trim();
  const command = resolveLocalComposerCommand(userText);
  if (!command) return null;

  if (command === 'files') {
    const files = normalizeArchiveSlugs(scopeOptions?.files || []);
    return {
      userText,
      assistantText: [
        'Available documents:',
        '',
        formatLocalSelectorHelpList(files, 'No documents are available yet.'),
        '',
        'Use `/file:DOCUMENT_NAME` at the start of your question to place the tag before the text.',
        'Example: `/file:RM797_ID_5515 summarize the contract rent`',
        '',
        'You can also type `@metadata` to inspect metadata fields first.',
      ].join('\n'),
    };
  }

  const metadataFields = normalizeMetadataFields(scopeOptions?.metadata_fields || []);
  return {
    userText,
    assistantText: [
      'Available metadata fields:',
      '',
      formatLocalSelectorHelpList(metadataFields, 'No metadata fields are available yet.'),
      '',
      'Use `@metadata` to prioritize metadata and add `/col:FIELD_NAME` before your question.',
      'Example: `@metadata /col:Región list the available regions`',
      '',
      'You can type `/files` to list the accessible documents.',
    ].join('\n'),
  };
}

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
  const sourcePreviewHighlightTerms = useMemo(
    () => buildSourceHighlightTerms(sourcePreviewEvidenceSnippet),
    [sourcePreviewEvidenceSnippet]
  );
  const sourcePreviewMarkdownComponents = useMemo(
    () => buildSourcePreviewMarkdownComponents(sourcePreviewHighlightTerms),
    [sourcePreviewHighlightTerms]
  );

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

  const resolveGraphNodeStatus = (nodeKey: string): NodeRuntimeStatus => {
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
  };

  const resolveNodeClassName = (status: NodeRuntimeStatus, selected?: boolean) => {
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
  };

  const resolveEdgeClassName = (edge: GraphDefinition['edges'][number]) => {
    const sourceStatus = resolveGraphNodeStatus(edge.source);
    const targetStatus = resolveGraphNodeStatus(edge.target);
    if (sourceStatus === 'failed' || targetStatus === 'failed') return 'stroke-rose-500';
    if (targetStatus === 'running') return 'stroke-blue-500';
    if (sourceStatus === 'completed' && targetStatus === 'completed') return 'stroke-emerald-500';
    if (sourceStatus === 'completed') return 'stroke-gray-400';
    return 'stroke-gray-300';
  };

  const formatNodeDuration = (durationMs: number) => {
    if (durationMs < 1) return '<1ms';
    if (durationMs < 1000) return `${Math.max(1, Math.round(durationMs))}ms`;
    if (durationMs < 10_000) return `${(durationMs / 1000).toFixed(1)}s`;
    return `${Math.round(durationMs / 1000)}s`;
  };

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
          const sources = mapSourcesFromMetadata(metadata);
          const citedSources = mapCitedSourcesFromMetadata(metadata, sources);
          const retrievedSources = mapSourcesByMetadataKey(metadata, 'retrieved_sources');
          return {
            messageId: String(item.message_id),
            role: item.role === 'user' ? 'user' : 'assistant',
            text: stripInlineSourcesSection(String(item.content || '')),
            timestamp: new Date(item.created_at),
            modelUsed: String(item.model_used || ''),
            sources,
            citedSources,
            retrievedSources: retrievedSources.length > 0 ? retrievedSources : sources,
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
        sources?: Source[];
        citedSources?: Source[];
        retrievedSources?: Source[];
        model_used?: string;
        reasoning?: ReasoningResult;
        telemetry?: Record<string, any>;
      };
      const reply = data?.reply ?? '';
      const sources = data?.sources ?? [];
      const citedSources = data?.citedSources ?? [];
      const retrievedSources = data?.retrievedSources ?? sources;
      setMessages((prev) => [
        ...prev,
        {
          messageId: `local-assistant-${Date.now()}`,
          role: 'assistant',
          text: stripInlineSourcesSection(reply || 'No response received.'),
          timestamp: new Date(),
          modelUsed: data?.model_used || '',
          sources,
          citedSources,
          retrievedSources,
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

  const renderComposer = (placeholder: string) => {
    let suggestionOffset = 0;
    const shouldRenderComposerOverlay =
      Boolean(input) && composerTokens.length > 0 && !composerHasActiveSelection;
    return (
      <div className="relative w-full">
        <div className="chat-composer-surface w-full rounded-2xl border border-oracle-border bg-white px-3 py-2 shadow-sm flex items-end gap-2">
          <div className="relative min-w-0 flex-1">
            {shouldRenderComposerOverlay ? (
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-x-0 top-0 max-h-56 overflow-hidden py-1 text-sm leading-6 text-oracle-dark-gray"
              >
                <div className="min-w-0 whitespace-pre-wrap break-words">
                  {composerVisualInlineParts.map((part) =>
                    part.type === 'text' ? (
                      <span key={part.id} className="whitespace-pre-wrap break-words">
                        {part.value}
                      </span>
                    ) : part.type === 'caret' ? (
                      <span
                        key={part.id}
                        className="mx-px inline-block h-5 w-px animate-pulse bg-oracle-dark-gray align-text-bottom"
                      />
                    ) : (
                      <span
                        key={part.id}
                        className={`${getInlineChipClassName(getComposerChipClassName(part.chip.tone))} align-middle`}
                        title={part.chip.label}
                      >
                        <SelectorChipIcon tone={part.chip.tone} />
                        <span className="min-w-0 truncate">{part.chip.label}</span>
                      </span>
                    )
                  )}
                </div>
              </div>
            ) : null}
            <textarea
              ref={composerInputRef}
              rows={1}
              value={input}
              onChange={(event) => handleComposerChange(event.target.value)}
              onFocus={() => {
                setComposerFocused(true);
                updateComposerCaret();
              }}
              onBlur={() => {
                setComposerFocused(false);
                setSelectedSuggestionIndex(0);
              }}
              onClick={updateComposerCaret}
              onKeyUp={updateComposerCaret}
              onSelect={updateComposerCaret}
              onKeyDown={handleComposerKeyDown}
              placeholder={placeholder}
              aria-label={placeholder}
              spellCheck={false}
              autoCorrect="off"
              autoCapitalize="off"
              autoComplete="off"
              data-gramm="false"
              data-gramm-editor="false"
              data-enable-grammarly="false"
              className={`chat-composer-input block max-h-56 min-h-8 min-w-[12rem] w-full resize-none overflow-hidden bg-transparent border-0 py-1 text-sm leading-6 outline-none ${
                shouldRenderComposerOverlay
                  ? 'chat-composer-input--overlay text-transparent caret-transparent placeholder:text-transparent decoration-transparent'
                  : 'text-oracle-dark-gray placeholder:text-oracle-medium-gray selection:bg-gray-200 selection:text-oracle-dark-gray'
              }`}
            />
          </div>
          <button
            type="button"
            onClick={() => void handleSearch()}
            disabled={loading || !input.trim()}
            className="mb-0.5 shrink-0 p-2 rounded-full bg-oracle-red text-white hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            title="Send"
            aria-label="Send"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 2L11 13" />
              <path d="M22 2L15 22L11 13L2 9L22 2Z" />
            </svg>
          </button>
        </div>
        {hasSelectorSuggestions ? (
          <div className="chat-suggestion-menu absolute bottom-[calc(100%+0.5rem)] left-0 right-0 z-30 max-h-[min(18rem,40vh)] overflow-x-hidden overflow-y-auto rounded-2xl border border-gray-200 bg-white shadow-xl">
            {selectorSuggestionState.groups.map((group) => {
              const startIndex = suggestionOffset;
              suggestionOffset += group.items.length;
              return (
                <div key={group.key} className="border-b border-gray-100 last:border-b-0">
                  <div className="px-3 pt-2 text-[10px] font-semibold uppercase tracking-wide text-oracle-light-gray">
                    {group.label}
                  </div>
                  <div className="p-2">
                    {group.items.map((item, itemIndex) => {
                      const suggestionIndex = startIndex + itemIndex;
                      const selected = suggestionIndex === selectedSuggestionIndex;
                      return (
                        <button
                          key={item.id}
                          type="button"
                          onMouseDown={(event) => event.preventDefault()}
                          onClick={() => applySelectorSuggestion(item)}
                          className={`flex w-full items-start justify-between gap-3 rounded-xl px-3 py-2 text-left transition-colors ${
                            selected
                              ? 'chat-suggestion-item-selected bg-gray-100 text-oracle-dark-gray ring-1 ring-inset ring-gray-200'
                              : 'hover:bg-gray-50 text-oracle-dark-gray'
                          }`}
                        >
                          <span className="min-w-0">
                            <span className="block truncate text-xs font-semibold">{item.label}</span>
                            {item.description ? (
                              <span className="block text-[11px] text-oracle-medium-gray">{item.description}</span>
                            ) : null}
                          </span>
                          <span className="chat-suggestion-kind-badge shrink-0 rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[10px] font-medium text-oracle-medium-gray">
                            {item.kind === 'file' ? 'Archivo' : item.kind === 'field' ? 'Campo' : 'Metadata'}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
    );
  };

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
      const pageMarkdown = extractDocumentPageMarkdown(markdown, source.page_number);
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

  const resolveSourcePreviewTarget = useCallback(
    (source: Source): Source | null => {
      const pageNumber = Number(source.page_number ?? 0);
      if (!Number.isFinite(pageNumber) || pageNumber <= 0) return null;
      if (source.file_id) {
        return { ...source, page_number: pageNumber };
      }
      return null;
    },
    []
  );

  const persistFeedbackEvent = (payload: Record<string, any>) => {
    try {
      const storageKey = 'rag-chat-feedback-events';
      const existingRaw = localStorage.getItem(storageKey);
      const existing = existingRaw ? JSON.parse(existingRaw) : [];
      const normalizedExisting = Array.isArray(existing) ? existing : [];
      const next = [payload, ...normalizedExisting].slice(0, 300);
      localStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      // no-op: feedback UI should still work without localStorage
    }
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
    persistFeedbackEvent({
      type: 'answer_feedback',
      value: alreadySelected ? 'cleared' : kind,
      conversation_id: activeConversationId ?? null,
      assistant_message_id: message.messageId,
      user_prompt: userPrompt,
      assistant_answer: message.text,
      created_at: new Date().toISOString(),
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
      persistFeedbackEvent({
        type: 'answer_copy',
        conversation_id: activeConversationId ?? null,
        assistant_message_id: message.messageId,
        user_prompt: userPrompt,
        assistant_answer: message.text,
        created_at: new Date().toISOString(),
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

          <div
            ref={listRef}
            className="chat-message-list flex-1 min-h-0 overflow-y-auto overflow-x-hidden p-4 flex flex-col gap-5 chat-scrollbar"
          >
            {loadingConversation ? (
              <div className="flex items-center justify-center h-full">
                <LoadingState size="sm" label="Loading chat..." textClassName="text-oracle-medium-gray" />
              </div>
            ) : (
              <>
                {messages.map((m, messageIndex) => {
                  const assistantHasMarkdownTable =
                    m.role === 'assistant' && messageContainsMarkdownTable(m.text);
                  const messageWidthClass =
                    m.role === 'assistant' && assistantHasMarkdownTable
                      ? 'w-full max-w-full'
                      : 'max-w-[85%]';
                  const userMessagePresentation =
                    m.role === 'user'
                      ? buildUserMessagePresentation(m.text, scopeOptions, m.telemetry)
                      : null;
                  const userMessageHasInlineChips = Boolean(
                    userMessagePresentation?.inlineParts.some((part) => part.type === 'chip')
                  );
                  const renderedMessageText =
                    m.role === 'user' && userMessagePresentation
                      ? userMessagePresentation.bodyText
                      : m.text;

                  return (
                    <div
                      key={m.messageId}
                      className={`flex gap-2.5 ${m.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}
                    >
                    {m.role === 'assistant' ? (
                      <div className="w-8 h-8 rounded-xl bg-oracle-red flex items-center justify-center flex-shrink-0 overflow-hidden mt-0.5">
                        {showAssistantAvatarImage ? (
                          <img
                            src={assistantAvatarUrl}
                            alt={assistantDisplayName}
                            className="w-full h-full object-cover rounded-xl"
                            onError={() => setAssistantAvatarImageFailed(true)}
                          />
                        ) : (
                          <span className="text-white text-xs font-bold">{assistantAvatarLetter}</span>
                        )}
                      </div>
                    ) : (
                      <div className="w-8 h-8 rounded-xl bg-oracle-dark-gray flex items-center justify-center flex-shrink-0 overflow-hidden mt-0.5">
                        <span className="text-white text-xs font-bold">{userInitials}</span>
                      </div>
                    )}

                    <div
                      className={`flex min-w-0 flex-col gap-1 ${messageWidthClass} ${m.role === 'user' ? 'items-end' : 'items-start'}`}
                    >
                      <div className="flex items-center gap-2 px-1">
                        <span className="text-[11px] font-semibold text-oracle-medium-gray">
                          {m.role === 'assistant' ? assistantDisplayName : (user?.name?.split(' ')[0] || 'You')}
                        </span>
                        <span className="text-[10px] text-oracle-light-gray">{formatTime(m.timestamp)}</span>
                      </div>

                      <div
                        className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm ${
                          m.role === 'user'
                            ? 'bg-oracle-dark-gray text-white rounded-tr-sm'
                            : m.error
                            ? 'bg-red-50 text-red-700 border border-red-200 rounded-tl-sm'
                            : 'chat-assistant-message bg-white text-oracle-dark-gray border border-gray-200 rounded-tl-sm overflow-hidden'
                        }`}
                      >
                        {m.role === 'user' && userMessagePresentation ? (
                          <div className="min-w-0 max-w-full overflow-hidden">
                            {userMessageHasInlineChips ? (
                              <div className="whitespace-pre-wrap break-words text-right text-sm leading-relaxed text-white">
                                {userMessagePresentation.inlineParts.map((part) =>
                                  part.type === 'text' ? (
                                    <span key={part.id} className="whitespace-pre-wrap break-words">
                                      {part.value}
                                    </span>
                                  ) : (
                                    <span
                                      key={part.id}
                                      className={`${getInlineChipClassName(getUserMessageChipClassName(part.chip.tone))} align-middle`}
                                      title={part.chip.label}
                                    >
                                      <SelectorChipIcon tone={part.chip.tone} />
                                      <span className="min-w-0 truncate">{part.chip.label}</span>
                                    </span>
                                  )
                                )}
                              </div>
                            ) : (
                              <div className="space-y-2 text-white">
                                <div className="whitespace-pre-wrap break-words text-right text-sm leading-relaxed">
                                  {renderedMessageText}
                                </div>
                                {userMessagePresentation.selectorChips.length > 0 ? (
                                  <div className="flex flex-wrap justify-end gap-1.5">
                                    {userMessagePresentation.selectorChips.map((chip) => (
                                      <span
                                        key={chip.id}
                                        className={getInlineChipClassName(getUserMessageChipClassName(chip.tone))}
                                        title={chip.label}
                                      >
                                        <SelectorChipIcon tone={chip.tone} />
                                        <span className="min-w-0 truncate">{chip.label}</span>
                                      </span>
                                    ))}
                                  </div>
                                ) : null}
                              </div>
                            )}
                          </div>
                        ) : (
                          <div className="min-w-0 max-w-full overflow-hidden">
                            <div className="max-w-none min-w-0 space-y-2 break-words text-sm leading-relaxed">
                              <ReactMarkdown
                                remarkPlugins={[remarkGfm]}
                                components={CHAT_MARKDOWN_COMPONENTS}
                              >
                                {renderedMessageText}
                              </ReactMarkdown>
                            </div>
                          </div>
                        )}
                        {m.role === 'assistant' && !m.error && formatInferredScopeLabel(m.telemetry) && (
                          <div className="mt-2 inline-flex items-center rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[10px] font-medium text-amber-800">
                            {formatInferredScopeLabel(m.telemetry)}
                          </div>
                        )}
                        {m.role === 'assistant' &&
                          (() => {
                            const citedSources = m.citedSources && m.citedSources.length > 0 ? m.citedSources : [];
                            const rawRetrievedSources =
                              m.retrievedSources && m.retrievedSources.length > 0
                                ? m.retrievedSources
                                : m.sources || [];
                            const fallbackSources = citedSources.length === 0 ? rawRetrievedSources : [];
                            if (citedSources.length === 0 && fallbackSources.length === 0) return null;

                            const renderSourceChip = (s: Source, index: number, keyPrefix: string) => {
                              const previewTarget = resolveSourcePreviewTarget(s);
                              const canOpenPreview = Boolean(previewTarget?.file_id && previewTarget?.page_number);
                              const resolvedPageNumber = Number(previewTarget?.page_number ?? s.page_number ?? 0);
                              const normalizedPageNumber =
                                Number.isFinite(resolvedPageNumber) && resolvedPageNumber > 0
                                  ? resolvedPageNumber
                                  : undefined;
                              const sourceLabel =
                                String(s.name || '').trim() || `page ${normalizedPageNumber ?? '?'}`;
                              return (
                                <button
                                  key={`${keyPrefix}-${s.doc_id}-${index}`}
                                  type="button"
                                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] max-w-[200px] transition-colors ${
                                    canOpenPreview
                                      ? 'bg-gray-100 border-gray-300 text-gray-700 hover:bg-gray-200'
                                      : 'bg-gray-50 border-gray-200 text-gray-500 cursor-default'
                                  }`}
                                  title={sourceLabel}
                                  onClick={() => {
                                    if (previewTarget) {
                                      void handleOpenSourcePreview(previewTarget);
                                    }
                                  }}
                                  disabled={!canOpenPreview}
                                >
                                  <svg className="w-2.5 h-2.5 flex-shrink-0 text-oracle-light-gray" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                  </svg>
                                  <span className="truncate">{sourceLabel}</span>
                                </button>
                              );
                            };

                            return (
                              <div className="mt-2 pt-1.5 space-y-2">
                                {citedSources.length > 0 && (
                                  <div>
                                    <p className="text-[10px] font-semibold text-oracle-light-gray uppercase tracking-wide mb-1.5">
                                      Cited in answer
                                    </p>
                                    <div className="flex flex-wrap gap-1.5">
                                      {citedSources.map((s, index) => renderSourceChip(s, index, 'cited'))}
                                    </div>
                                  </div>
                                )}
                                {fallbackSources.length > 0 && (
                                  <div>
                                    <p className="text-[10px] font-semibold text-oracle-light-gray uppercase tracking-wide mb-1.5">
                                      Sources
                                    </p>
                                    <div className="flex flex-wrap gap-1.5">
                                      {fallbackSources.map((s, index) => renderSourceChip(s, index, 'fallback'))}
                                    </div>
                                  </div>
                                )}
                              </div>
                            );
                          })()}
                      </div>
                      {m.role === 'assistant' && !m.error && (
                        <div className="-mt-1 px-1">
                          <div className="inline-flex items-center gap-2">
                            <button
                              type="button"
                              className={`inline-flex items-center justify-center transition-colors ${
                                copiedMessageId === m.messageId
                                  ? 'text-emerald-600'
                                  : 'text-oracle-medium-gray hover:text-oracle-dark-gray'
                              } hover:drop-shadow-[0_2px_4px_rgba(0,0,0,0.25)]`}
                              title="Copy answer"
                              aria-label="Copy answer"
                              onClick={() => void handleCopyAssistantAnswer(m, messageIndex)}
                            >
                              <svg className="w-[15px] h-[15px]" fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                <path d="M21,8H9A1,1,0,0,0,8,9V21a1,1,0,0,0,1,1H21a1,1,0,0,0,1-1V9A1,1,0,0,0,21,8ZM20,20H10V10H20ZM6,15a1,1,0,0,1-1,1H3a1,1,0,0,1-1-1V3A1,1,0,0,1,3,2H15a1,1,0,0,1,1,1V5a1,1,0,0,1-2,0V4H4V14H5A1,1,0,0,1,6,15Z" />
                              </svg>
                            </button>
                            <button
                              type="button"
                              className={`inline-flex items-center justify-center transition-colors ${
                                messageFeedback[m.messageId] === 'up'
                                  ? 'text-emerald-600'
                                  : 'text-oracle-medium-gray hover:text-oracle-dark-gray'
                              } hover:drop-shadow-[0_2px_4px_rgba(0,0,0,0.25)]`}
                              title="Helpful response"
                              aria-label="Mark response as helpful"
                              onClick={() => handleMessageFeedback(m, messageIndex, 'up')}
                            >
                              <svg className="w-[15px] h-[15px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth={1.8}
                                  d="M14 9V5a3 3 0 00-3-3l-1 5-3 4v10h10.5a2.5 2.5 0 002.45-2l1-7A2.5 2.5 0 0018.5 9H14z"
                                />
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M7 11H4a1 1 0 00-1 1v8a1 1 0 001 1h3" />
                              </svg>
                            </button>
                            <button
                              type="button"
                              className={`inline-flex items-center justify-center transition-colors ${
                                messageFeedback[m.messageId] === 'down'
                                  ? 'text-rose-600'
                                  : 'text-oracle-medium-gray hover:text-oracle-dark-gray'
                              } hover:drop-shadow-[0_2px_4px_rgba(0,0,0,0.25)]`}
                              title="Not helpful response"
                              aria-label="Mark response as not helpful"
                              onClick={() => handleMessageFeedback(m, messageIndex, 'down')}
                            >
                              <svg className="w-[15px] h-[15px] rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth={1.8}
                                  d="M14 9V5a3 3 0 00-3-3l-1 5-3 4v10h10.5a2.5 2.5 0 002.45-2l1-7A2.5 2.5 0 0018.5 9H14z"
                                />
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M7 11H4a1 1 0 00-1 1v8a1 1 0 001 1h3" />
                              </svg>
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                    </div>
                  );
                })}

                {loading && (
                  <div className="flex gap-2.5 flex-row">
                    <div className="w-8 h-8 rounded-xl bg-oracle-red flex items-center justify-center flex-shrink-0 overflow-hidden mt-0.5">
                      {showAssistantAvatarImage ? (
                        <img
                          src={assistantAvatarUrl}
                          alt={assistantDisplayName}
                          className="w-full h-full object-cover rounded-xl"
                          onError={() => setAssistantAvatarImageFailed(true)}
                        />
                      ) : (
                        <span className="text-white text-xs font-bold">{assistantAvatarLetter}</span>
                      )}
                    </div>
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center gap-2 px-1">
                        <span className="text-[11px] font-semibold text-oracle-medium-gray">{assistantDisplayName}</span>
                        <span className="text-[10px] text-oracle-light-gray">{`${loadingElapsedSeconds} seg`}</span>
                      </div>
                      <div className="rounded-2xl rounded-tl-sm px-4 py-3 bg-white border border-gray-200 shadow-sm flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-oracle-light-gray animate-bounce" style={{ animationDelay: '0ms' }} />
                        <span className="w-1.5 h-1.5 rounded-full bg-oracle-light-gray animate-bounce" style={{ animationDelay: '150ms' }} />
                        <span className="w-1.5 h-1.5 rounded-full bg-oracle-light-gray animate-bounce" style={{ animationDelay: '300ms' }} />
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
          <div className="chat-composer-footer p-3 border-t border-oracle-border flex-shrink-0 bg-white">
            {renderComposer(composerPlaceholder)}
          </div>
        </>
      )}
      {!isInitialCentered && isGraphPanelOpen && (
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
                onClick={() => setIsGraphPanelOpen(false)}
                aria-label="Close graph panel"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4 bg-oracle-bg-gray">
            {graphDefinitionQuery.isLoading && (
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
                      onClick={() => adjustGraphZoom(-0.1)}
                      title="Zoom out"
                      aria-label="Zoom out"
                    >
                      -
                    </button>
                    <button
                      type="button"
                      className="px-2 h-6 rounded border border-gray-300 bg-white text-[10px] text-gray-700 hover:bg-gray-50"
                      onClick={resetGraphZoom}
                      title="Reset zoom"
                      aria-label="Reset zoom"
                    >
                      {`${Math.round(graphZoom * 100)}%`}
                    </button>
                    <button
                      type="button"
                      className="h-6 w-6 rounded border border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
                      onClick={() => adjustGraphZoom(0.1)}
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
                onMouseDown={handleGraphPanStart}
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
                        onClick={() => setSelectedGraphNodeKey(node.key)}
                        onKeyDown={(event: React.KeyboardEvent<SVGGElement>) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            setSelectedGraphNodeKey(node.key);
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
      )}
      </div>
      <GlassModal
        open={isSourcePreviewOpen}
        onClose={() => setIsSourcePreviewOpen(false)}
        containerClassName="items-start justify-center p-4"
        panelClassName="w-full max-w-6xl mt-8 border-0 overflow-hidden"
      >
        <div className="px-5 py-4 flex items-center gap-3 bg-oracle-dark-gray">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-white truncate">Source Page Preview</h2>
            {sourcePreviewTitle && (
              <p className="text-xs text-gray-300 truncate" title={sourcePreviewTitle}>
                {sourcePreviewTitle}
              </p>
            )}
          </div>
          <div className="ml-auto" />
          <button
            type="button"
            onClick={() => setIsSourcePreviewOpen(false)}
            className="p-1.5 rounded-lg hover:bg-white/10 transition-colors text-gray-200"
            aria-label="Close source preview"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="p-0 bg-white/80 h-[78vh] min-h-[500px] overflow-hidden">
          {sourcePreviewLoading ? (
            <div className="h-full min-h-[360px] flex items-center justify-center">
              <LoadingState size="sm" label="Loading cited page..." textClassName="text-oracle-medium-gray" />
            </div>
          ) : (
            <div className="grid h-full min-h-0 grid-cols-1 overflow-hidden md:grid-cols-2">
              <div className="flex min-h-0 flex-col border-r border-oracle-border">
                <div className="flex min-h-[46px] flex-shrink-0 items-center justify-between border-b border-oracle-border bg-gray-50 px-4 py-2">
                  <span className="text-sm font-medium text-oracle-dark-gray">Page Image Preview</span>
                  <span className="text-xs text-oracle-light-gray">
                    Page {sourcePreviewPageNumber || '?'}
                  </span>
                </div>
                <div className="min-h-0 flex-1 overflow-auto bg-white">
                  {sourcePreviewImageUri ? (
                    <div className="flex min-h-full items-start justify-center bg-white">
                      <img
                        src={sourcePreviewImageUri}
                        alt={sourcePreviewTitle || 'Source page'}
                        className="block w-full max-w-none bg-white"
                      />
                    </div>
                  ) : (
                    <div className="m-4 flex h-[calc(100%-2rem)] min-h-[320px] items-center justify-center rounded-xl border border-dashed border-gray-300 bg-white px-6 text-center">
                      <div>
                        <p className="text-sm font-medium text-oracle-dark-gray">Preview unavailable</p>
                        <p className="mt-1 text-xs leading-5 text-oracle-light-gray">
                          {sourcePreviewImageError || 'The rendered page image was not generated for this page.'}
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className="flex min-h-0 flex-col overflow-hidden">
                <div className="flex min-h-[46px] flex-shrink-0 items-center justify-between border-b border-oracle-border bg-gray-50 px-4 py-2">
                  <span className="text-sm font-medium text-oracle-dark-gray">Markdown Content</span>
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      disabled
                      className="p-1.5 rounded border border-gray-300 text-gray-400 opacity-40 cursor-not-allowed"
                      title="Previous page disabled for cited-page preview"
                      aria-label="Previous page"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                      </svg>
                    </button>
                    <button
                      type="button"
                      disabled
                      className="p-1.5 rounded border border-gray-300 text-gray-400 opacity-40 cursor-not-allowed"
                      title="Next page disabled for cited-page preview"
                      aria-label="Next page"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </button>
                    <button
                      type="button"
                      onClick={copySourcePreviewMarkdown}
                      disabled={Boolean(sourcePreviewMarkdownError || !sourcePreviewMarkdown)}
                      className="p-1.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed"
                      title="Copy Markdown"
                      aria-label="Copy Markdown"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                      </svg>
                    </button>
                  </div>
                </div>
                <div className="min-h-0 flex-1 overflow-auto bg-white p-3">
                  {sourcePreviewMarkdownError ? (
                    <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800">
                      {sourcePreviewMarkdownError}
                    </div>
                  ) : (
                    <div className="prose prose-sm max-w-none text-[13px] leading-5 text-oracle-dark-gray [&_h1]:mb-2 [&_h1]:mt-4 [&_h1]:text-lg [&_h1]:font-bold [&_mark]:box-decoration-clone">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={sourcePreviewMarkdownComponents}>
                        {sourcePreviewMarkdown}
                      </ReactMarkdown>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </GlassModal>
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
