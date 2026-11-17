import type { RAGScopeOptions } from '../../lib/chatSelectors';
import { normalizeArchiveSlugs, normalizeMetadataFields } from '../../lib/chatSelectors';
import type { Message, ReasoningResult, Source } from './RAGChatPanel.types';
const LOCAL_SELECTOR_HELP_LIST_LIMIT = 18;
export function buildMessageMergeSignature(message: Message): string {
  const normalizedText = String(message.text || '').trim().replace(/\s+/g, ' ');
  return `${message.role}::${normalizedText}`;
}

export function mergeLoadedConversationMessages(loaded: Message[], optimistic: Message[]): Message[] {
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

export function formatJsonForDisplay(value: unknown): string {
  if (value === undefined) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function extractNodeResponseText(value: unknown): string {
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

export function mapSourcesFromArray(sourceItems: Array<Record<string, any>>): Source[] {
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

export function mapSourcesByMetadataKey(metadata: Record<string, any>, key: string): Source[] {
  const sourceItems = Array.isArray(metadata?.[key]) ? (metadata[key] as Array<Record<string, any>>) : [];
  if (sourceItems.length === 0) return [];
  return mapSourcesFromArray(sourceItems);
}

export function mapCitedSourcesFromMetadata(metadata: Record<string, any>): Source[] {
  return mapSourcesByMetadataKey(metadata, 'cited_sources');
}

export function mapReasoningFromMetadata(metadata: Record<string, any>): ReasoningResult | undefined {
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

export function formatInferredScopeLabel(telemetry?: Record<string, any>): string {
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

export type LocalComposerCommandKind = 'files' | 'metadata';

export function resolveLocalComposerCommand(value: string): LocalComposerCommandKind | null {
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

export function formatLocalSelectorHelpList(values: string[], emptyMessage: string): string {
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

export function buildLocalComposerCommandMessages(
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
      'Example: `@metadata /col:RegiÃ³n list the available regions`',
      '',
      'You can type `/files` to list the accessible documents.',
    ].join('\n'),
  };
}
