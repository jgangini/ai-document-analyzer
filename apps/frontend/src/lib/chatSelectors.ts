const FILE_EXTENSION_PATTERN = /\.(?:zip|pdf)\b/i;
const WHITESPACE_PATTERN = /\s+/g;

export type RAGScopeOptions = {
  files: string[];
  metadata_fields: string[];
  has_metadata: boolean;
};

export type ParsedChatSelectors = {
  cleanedQuestion: string;
  metadataMode: 'auto' | 'metadata_first';
  archiveSlugs: string[];
  metadataFields: string[];
};

export type ParsedChatSelectorToken = {
  kind: 'metadata' | 'file' | 'field';
  start: number;
  end: number;
  label: string;
  raw: string;
};

export type ParsedChatSelectorsDetailed = ParsedChatSelectors & {
  tokens: ParsedChatSelectorToken[];
};

function normalizeSelectorText(value: string | null | undefined): string {
  return String(value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}

export function canonicalizeArchiveSlug(value: string | null | undefined): string {
  return String(value || '')
    .trim()
    .replace(FILE_EXTENSION_PATTERN, '')
    .replace(/^[\s,.;:]+|[\s,.;:]+$/g, '')
    .toUpperCase();
}

export function normalizeArchiveSlugs(values: string[] | null | undefined): string[] {
  const seen = new Set<string>();
  const ordered: string[] = [];
  for (const rawValue of values || []) {
    const normalized = canonicalizeArchiveSlug(rawValue);
    const key = normalized.toLowerCase();
    if (!normalized || seen.has(key)) continue;
    seen.add(key);
    ordered.push(normalized);
  }
  return ordered;
}

export function normalizeMetadataFields(values: string[] | null | undefined): string[] {
  const seen = new Set<string>();
  const ordered: string[] = [];
  for (const rawValue of values || []) {
    const normalized = String(rawValue || '').trim();
    const key = normalizeSelectorText(normalized);
    if (!normalized || seen.has(key)) continue;
    seen.add(key);
    ordered.push(normalized);
  }
  return ordered;
}

function hasSelectorBoundary(text: string, index: number): boolean {
  return index <= 0 || /\s/.test(text[index - 1] || '');
}

function consumeSeparator(text: string, index: number): number {
  let cursor = index;
  while (cursor < text.length && /\s/.test(text[cursor] || '')) cursor += 1;
  if (cursor < text.length && [',', ';'].includes(text[cursor] || '')) {
    cursor += 1;
    while (cursor < text.length && /\s/.test(text[cursor] || '')) cursor += 1;
  }
  return cursor;
}

function consumeQuotedValue(text: string, start: number): [string, number] | null {
  const quote = text[start];
  if (!quote || (quote !== '"' && quote !== "'")) return null;
  let cursor = start + 1;
  while (cursor < text.length) {
    if (text[cursor] === quote) {
      return [text.slice(start + 1, cursor), cursor + 1];
    }
    cursor += 1;
  }
  return null;
}

function resolveArchiveSlugCatalog(value: string, catalog: string[]): string | null {
  const canonicalValue = canonicalizeArchiveSlug(value);
  const normalizedValue = canonicalValue.toLowerCase();
  for (const candidate of catalog) {
    if (canonicalizeArchiveSlug(candidate).toLowerCase() === normalizedValue) {
      return candidate;
    }
  }
  return null;
}

function matchCatalogArchiveSlug(text: string, start: number, catalog: string[]): [string, number] | null {
  const segment = text.slice(start).toLowerCase();
  const candidates = [...normalizeArchiveSlugs(catalog)].sort((left, right) => right.length - left.length);
  for (const candidate of candidates) {
    const loweredCandidate = candidate.toLowerCase();
    for (const suffix of ['', '.zip', '.pdf']) {
      const rendered = `${loweredCandidate}${suffix}`;
      if (!segment.startsWith(rendered)) continue;
      const end = start + rendered.length;
      const delimiter = text[end];
      if (delimiter && !/\s/.test(delimiter) && ![',', ';'].includes(delimiter)) continue;
      return [candidate, end];
    }
  }
  return null;
}

function matchCatalogMetadataField(text: string, start: number, catalog: string[]): [string, number] | null {
  const segment = text.slice(start).toLowerCase();
  const candidates = [...normalizeMetadataFields(catalog)].sort((left, right) => right.length - left.length);
  for (const candidate of candidates) {
    if (!segment.startsWith(candidate.toLowerCase())) continue;
    const end = start + candidate.length;
    const delimiter = text[end];
    if (delimiter && !/\s/.test(delimiter) && ![',', ';'].includes(delimiter)) continue;
    return [candidate, end];
  }
  return null;
}

function consumeUnquotedFileValue(text: string, start: number, catalog: string[] | null): [string, number] | null {
  let cursor = start;
  while (cursor < text.length && !/\s/.test(text[cursor] || '') && ![',', ';'].includes(text[cursor] || '')) {
    cursor += 1;
  }
  const rawValue = text.slice(start, cursor).trim();
  if (!rawValue) return null;
  if (catalog && catalog.length > 0) {
    const resolved = resolveArchiveSlugCatalog(rawValue, catalog);
    if (resolved) return [resolved, cursor];
  }
  const canonical = canonicalizeArchiveSlug(rawValue);
  return canonical ? [canonical, cursor] : null;
}

function consumeUnquotedFieldValue(text: string, start: number, catalog: string[] | null): [string, number] | null {
  if (catalog && catalog.length > 0) {
    const matched = matchCatalogMetadataField(text, start, catalog);
    if (matched) return matched;
  }
  let cursor = start;
  while (cursor < text.length) {
    if ([',', ';'].includes(text[cursor] || '')) break;
    if (/\s/.test(text[cursor] || '')) {
      let lookahead = cursor;
      while (lookahead < text.length && /\s/.test(text[lookahead] || '')) lookahead += 1;
      const remainder = text.slice(lookahead).toLowerCase();
      if (remainder.startsWith('@metadata') || remainder.startsWith('/file:') || remainder.startsWith('/col:')) {
        break;
      }
    }
    cursor += 1;
  }
  const rawValue = text.slice(start, cursor).trim();
  return rawValue ? [rawValue, cursor] : null;
}

export function parseChatSelectorsDetailed(params: {
  question: string;
  scopeOptions?: Pick<RAGScopeOptions, 'files' | 'metadata_fields'> | null;
}): ParsedChatSelectorsDetailed {
  const text = String(params.question || '');
  const archiveCatalog = normalizeArchiveSlugs(params.scopeOptions?.files || []);
  const fieldCatalog = normalizeMetadataFields(params.scopeOptions?.metadata_fields || []);

  let metadataRequested = false;
  const archiveSlugs: string[] = [];
  const metadataFields: string[] = [];
  const consumedRanges: Array<[number, number]> = [];
  const tokens: ParsedChatSelectorToken[] = [];

  let cursor = 0;
  while (cursor < text.length) {
    if (text[cursor] === '@' && hasSelectorBoundary(text, cursor)) {
      if (text.slice(cursor, cursor + 9).toLowerCase() === '@metadata') {
        metadataRequested = true;
        const tokenEnd = cursor + 9;
        tokens.push({
          kind: 'metadata',
          start: cursor,
          end: tokenEnd,
          label: 'Metadata',
          raw: text.slice(cursor, tokenEnd),
        });
        const end = consumeSeparator(text, tokenEnd);
        consumedRanges.push([cursor, end]);
        cursor = end;
        continue;
      }
    }

    if (text[cursor] === '/' && hasSelectorBoundary(text, cursor)) {
      if (text.slice(cursor, cursor + 6).toLowerCase() === '/file:') {
        let valueStart = cursor + 6;
        while (valueStart < text.length && /\s/.test(text[valueStart] || '')) valueStart += 1;
        let matched: [string, number] | null = null;
        const quoted = consumeQuotedValue(text, valueStart);
        if (quoted) {
          const [rawValue, end] = quoted;
          matched = [resolveArchiveSlugCatalog(rawValue, archiveCatalog) || canonicalizeArchiveSlug(rawValue), end];
        } else if (archiveCatalog.length > 0) {
          matched = matchCatalogArchiveSlug(text, valueStart, archiveCatalog) || consumeUnquotedFileValue(text, valueStart, archiveCatalog);
        } else {
          matched = consumeUnquotedFileValue(text, valueStart, null);
        }
        if (matched && matched[0]) {
          archiveSlugs.push(matched[0]);
          const tokenEnd = matched[1];
          tokens.push({
            kind: 'file',
            start: cursor,
            end: tokenEnd,
            label: matched[0],
            raw: text.slice(cursor, tokenEnd),
          });
          const end = consumeSeparator(text, tokenEnd);
          consumedRanges.push([cursor, end]);
          cursor = end;
          continue;
        }
      }

      if (text.slice(cursor, cursor + 5).toLowerCase() === '/col:') {
        let valueStart = cursor + 5;
        while (valueStart < text.length && /\s/.test(text[valueStart] || '')) valueStart += 1;
        let matched: [string, number] | null = null;
        const quoted = consumeQuotedValue(text, valueStart);
        if (quoted) {
          matched = quoted;
        } else {
          matched = consumeUnquotedFieldValue(text, valueStart, fieldCatalog);
        }
        if (matched && String(matched[0]).trim()) {
          const label = String(matched[0]).trim();
          metadataFields.push(label);
          const tokenEnd = matched[1];
          tokens.push({
            kind: 'field',
            start: cursor,
            end: tokenEnd,
            label,
            raw: text.slice(cursor, tokenEnd),
          });
          const end = consumeSeparator(text, tokenEnd);
          consumedRanges.push([cursor, end]);
          cursor = end;
          continue;
        }
      }
    }

    cursor += 1;
  }

  let cleanedQuestion = '';
  if (consumedRanges.length === 0) {
    cleanedQuestion = text.replace(WHITESPACE_PATTERN, ' ').trim();
  } else {
    const parts: string[] = [];
    let start = 0;
    for (const [rangeStart, rangeEnd] of consumedRanges) {
      if (rangeStart > start) parts.push(text.slice(start, rangeStart));
      start = Math.max(start, rangeEnd);
    }
    if (start < text.length) parts.push(text.slice(start));
    cleanedQuestion = parts.join('').replace(WHITESPACE_PATTERN, ' ').trim();
  }

  const normalizedMetadataFields = normalizeMetadataFields(metadataFields);
  return {
    cleanedQuestion,
    metadataMode: metadataRequested || normalizedMetadataFields.length > 0 ? 'metadata_first' : 'auto',
    archiveSlugs: normalizeArchiveSlugs(archiveSlugs),
    metadataFields: normalizedMetadataFields,
    tokens,
  };
}

export function parseChatSelectors(params: {
  question: string;
  scopeOptions?: Pick<RAGScopeOptions, 'files' | 'metadata_fields'> | null;
}): ParsedChatSelectors {
  const detailed = parseChatSelectorsDetailed(params);
  return {
    cleanedQuestion: detailed.cleanedQuestion,
    metadataMode: detailed.metadataMode,
    archiveSlugs: detailed.archiveSlugs,
    metadataFields: detailed.metadataFields,
  };
}
