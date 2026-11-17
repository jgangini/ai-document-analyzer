import type { ParsedChatSelectorToken, ParsedChatSelectors, RAGScopeOptions } from '../../lib/chatSelectors';
import {
  normalizeArchiveSlugs,
  normalizeMetadataFields,
  parseChatSelectors,
  parseChatSelectorsDetailed,
} from '../../lib/chatSelectors';
export const COMPOSER_TOKEN_PLACEHOLDER_BASE_SPACES = 2;
export const COMPOSER_TOKEN_PLACEHOLDER_MIN_LENGTH = 10;
export const COMPOSER_METADATA_TOKEN_PLACEHOLDER_MIN_LENGTH = 12;
export const LOCAL_SELECTOR_HELP_LIST_LIMIT = 18;

export type ChatRequestOptions = {
  allow_inferred_scope?: boolean;
  top_k?: number;
  candidate_k?: number;
  min_pages_per_selected_doc?: number;
  summary_mode?: 'default' | 'per_document';
  metadata_mode?: 'auto' | 'metadata_first';
  archive_slugs?: string[];
  metadata_fields?: string[];
};

export type ChatRequestBuildResult = {
  cleanedQuestion: string;
  selectors: ParsedChatSelectors;
  requestOptions: ChatRequestOptions;
  metadataRequestedExplicitly: boolean;
};

export type ComposerSelectorState = {
  metadataMode: 'auto' | 'metadata_first';
  archiveSlugs: string[];
  metadataFields: string[];
  metadataRequestedExplicitly: boolean;
};

export type SelectorSuggestion = {
  id: string;
  label: string;
  description?: string;
  replacement: string;
  group: 'special' | 'files' | 'metadata';
  kind: 'metadata' | 'file' | 'field';
};

export type SelectorSuggestionGroup = {
  key: 'special' | 'files' | 'metadata';
  label: string;
  items: SelectorSuggestion[];
};

export type UserMessageSelectorChipTone = 'metadata' | 'file' | 'field';

export type UserMessageSelectorChip = {
  id: string;
  label: string;
  tone: UserMessageSelectorChipTone;
};

export type UserMessagePresentation = {
  bodyText: string;
  selectorChips: UserMessageSelectorChip[];
  inlineParts: Array<
    | { id: string; type: 'text'; value: string }
    | { id: string; type: 'chip'; chip: UserMessageSelectorChip; token?: ParsedChatSelectorToken }
  >;
};

export type ComposerInlinePart =
  | UserMessagePresentation['inlineParts'][number]
  | { id: string; type: 'caret' };

export function buildChatRequestOptionsFromComposer(
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

export function buildEffectiveComposerQuestionText(requestBuild: ChatRequestBuildResult): string {
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

export function shouldUsePerDocumentSummary(question: string, archiveSlugs: string[]): boolean {
  if (!archiveSlugs.length) return false;
  const normalized = String(question || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase();
  return [
    'por documento',
    'por archivo',
    'cada documento',
    'cada archivo',
    'separa por',
    'agrupa por',
    'compara',
    'comparar',
    'diferencia',
    'diferencias',
    'similitud',
    'similitudes',
    'evidencia',
    'cita',
    'citas',
    'fuente',
    'fuentes',
    'pagina',
    'paginas',
    'page',
    'pages',
    'documentos relevantes',
    'archivos relevantes',
    'which documents',
    'what documents',
    'relevant documents',
  ].some((term) => normalized.includes(term));
}

export function getSelectorSearchContext(value: string, caret: number): { token: string; start: number; end: number } | null {
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

export function getSelectorSuggestionMatchRank(value: string, query: string): [number, number, number] {
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

export function rankSelectorSuggestionValue(left: string, right: string, query: string): number {
  const leftRank = getSelectorSuggestionMatchRank(left, query);
  const rightRank = getSelectorSuggestionMatchRank(right, query);
  if (leftRank[0] !== rightRank[0]) return leftRank[0] - rightRank[0];
  if (leftRank[1] !== rightRank[1]) return leftRank[1] - rightRank[1];
  if (leftRank[2] !== rightRank[2]) return leftRank[2] - rightRank[2];
  return left.localeCompare(right);
}

export function getSlashSelectorIntent(token: string): {
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

export function buildSelectorSuggestionGroups(
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

export function buildSelectorStateFromTelemetry(telemetry?: Record<string, any>): ComposerSelectorState {
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

export function removeComposerToken(value: string, start: number, end: number): { nextValue: string; nextCaret: number } {
  const before = value.slice(0, start);
  const after = value.slice(end);
  const needsSpace = Boolean(before && after && !/\s$/.test(before) && !/^\s/.test(after));
  const nextValue = `${before}${needsSpace ? ' ' : ''}${after}`.replace(/\s{2,}/g, ' ').trimStart();
  const nextCaret = Math.min(start, nextValue.length);
  return { nextValue, nextCaret };
}

export function replaceComposerToken(
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

export function serializeComposerInput(value: string, tokens: ParsedChatSelectorToken[]): string {
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

export function reconcileComposerTokens(
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

export function buildComposerTokenPayload(suggestion: SelectorSuggestion): Pick<ParsedChatSelectorToken, 'kind' | 'label' | 'raw'> {
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

export function insertComposerTokenLabel(
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

export function buildSelectorChips(selectorState: ComposerSelectorState): UserMessageSelectorChip[] {
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

export function buildSelectorChipFromToken(token: ParsedChatSelectorToken): UserMessageSelectorChip {
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

export function buildInlineSelectorParts(
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

export function buildComposerVisualInlineParts(
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

export function buildUserMessagePresentation(
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
      label: `Archivo Â· ${archiveSlug}`,
      tone: 'file',
    });
  }

  for (const metadataField of [] as string[]) {
    selectorChips.push({
      id: `field-${metadataField}`,
      label: `Columna Â· ${metadataField}`,
      tone: 'field',
    });
  }

  return {
    bodyText: parsed.cleanedQuestion.trim() || rawText,
    selectorChips,
    inlineParts: buildInlineSelectorParts(rawText, parsed.tokens),
  };
}

export function getUserMessageChipClassName(_tone: UserMessageSelectorChipTone): string {
  return 'border-white/15 bg-white/10 text-white/95';
}

export function getComposerChipClassName(_tone: UserMessageSelectorChipTone): string {
  return 'composer-token-chip border-gray-200 bg-white text-oracle-dark-gray';
}

export function getInlineChipClassName(baseClassName: string): string {
  return `inline-flex h-4 max-w-[18rem] items-center gap-0.5 whitespace-nowrap rounded-full border px-1.5 py-0 text-[10px] font-medium leading-none sm:max-w-[22rem] ${baseClassName}`;
}

export function SelectorChipIcon({ tone }: { tone: UserMessageSelectorChipTone }) {
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
