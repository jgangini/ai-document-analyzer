import React from 'react';

import type { UploadPreparationGroup, UploadPreparationItem } from '../../services/apiTypes';
export const ITEMS_PER_PAGE = 10;
export const DEFAULT_UPLOAD_LANGUAGE = 'es';
export const DEFAULT_UPLOAD_ACCESS = 'private';
export const LANGUAGE_OPTIONS = [
  { value: 'es', label: 'Spanish (es)' },
  { value: 'pt', label: 'Portuguese (pt)' },
  { value: 'en', label: 'English (en)' },
];
export const ACCESS_OPTIONS = [
  { value: 'private', label: 'Private' },
  { value: 'all', label: 'All Users' },
];

export function normalizeStatus(status: string | undefined): string {
  const value = String(status || '').toLowerCase().trim();
  if (value === 'registered') return 'pending';
  if (value === 'processing') return 'processing_ocr';
  if (value === 'failed') return 'error';
  return value || 'pending';
}

export function extractFolderFromObjectPath(objectPath: string): string {
  const normalizedPath = String(objectPath || '').trim().replace(/\\/g, '/');
  if (!normalizedPath) return '';
  const segments = normalizedPath.split('/').filter(Boolean);
  const sourceIndex = segments.findIndex((segment) =>
    ['source', 'sources', 'processed', 'output', 'outputs', 'ocr'].includes(
      segment.toLowerCase()
    )
  );
  if (sourceIndex <= 1) return '';
  const directFolder = segments[sourceIndex - 1] || '';
  const parentFolder = segments[sourceIndex - 2] || '';
  if (parentFolder && /-[a-f0-9]{8,}$/i.test(parentFolder)) {
    return parentFolder.replace(/-[a-f0-9]{8,}$/i, '');
  }
  return directFolder;
}

export function normalizeComparableSegment(value: string): string {
  return String(value || '')
    .toLowerCase()
    .replace(/\.[a-z0-9]+$/i, '')
    .replace(/[^a-z0-9]+/g, '');
}

export function getDocumentDisplayName(doc: any): string {
  const fileName = String(doc?.original_name || doc?.filename || '').trim();
  if (!fileName) return '-';
  const objectPath = String(doc?.file_output_obj_name || doc?.file_input_obj_name || '');
  const folder = extractFolderFromObjectPath(objectPath);
  if (!folder) return fileName;
  const normalizedFolder = normalizeComparableSegment(folder);
  const normalizedFileStem = normalizeComparableSegment(fileName);
  if (normalizedFolder && normalizedFolder === normalizedFileStem) {
    return fileName;
  }
  return `${folder}/${fileName}`;
}

export function DeleteDocumentConfirmMessage({ docNames }: { docNames: string[] }) {
  const normalizedNames = docNames
    .map((value) => String(value || '').trim())
    .filter(Boolean);
  if (normalizedNames.length > 1) {
    return (
      <div className="space-y-2 text-sm leading-relaxed text-oracle-medium-gray">
        <p>
          Are you sure you want to delete <span className="font-medium text-oracle-dark-gray">{normalizedNames.length}</span>{' '}
          selected documents?
        </p>
        <p>This action cannot be undone.</p>
      </div>
    );
  }
  const name = normalizedNames[0] || 'this document';
  return (
    <div className="flex w-full min-w-0 max-w-full flex-nowrap items-baseline gap-x-0.5 text-sm leading-relaxed text-oracle-medium-gray">
      <span className="shrink-0">Are you sure you want to delete &quot;</span>
      <span
        className="min-w-0 flex-1 truncate text-center font-medium text-oracle-dark-gray"
        title={name}
      >
        {name}
      </span>
      <span className="shrink-0">&quot;?</span>
    </div>
  );
}

export type LooseMarkdownTable = {
  caption?: string;
  headers: string[];
  rows: string[][];
};

export function splitLooseTableCells(value: string): string[] {
  const rawCells = String(value || '')
    .replace(/\r/g, '')
    .split('|')
    .map((cell) => cell.replace(/\s+/g, ' ').trim());

  while (rawCells.length > 0 && rawCells[0] === '') rawCells.shift();
  while (rawCells.length > 0 && rawCells[rawCells.length - 1] === '') rawCells.pop();
  return rawCells;
}

export function isMarkdownSeparatorCell(value: string): boolean {
  return /^:?-{2,}:?$/.test(String(value || '').trim());
}

export function parseLooseMarkdownTable(value: string): LooseMarkdownTable | null {
  const text = String(value || '').replace(/\r/g, '').trim();
  if (!text || (text.match(/\|/g) || []).length < 4) return null;

  const separatorMatch = text.match(/\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?/);
  if (!separatorMatch || separatorMatch.index === undefined) return null;

  const beforeSeparator = text.slice(0, separatorMatch.index).trim();
  const afterSeparator = text.slice(separatorMatch.index + separatorMatch[0].length).trim();
  const separatorCells = splitLooseTableCells(separatorMatch[0]).filter(isMarkdownSeparatorCell);
  let caption = '';
  let headers = splitLooseTableCells(beforeSeparator);
  const columnCount = Math.max(separatorCells.length, headers.length);

  if (columnCount < 2 || headers.length < 2) return null;
  if (separatorCells.length >= 2 && headers.length > separatorCells.length) {
    caption = headers.slice(0, headers.length - separatorCells.length).join(' | ');
    headers = headers.slice(headers.length - separatorCells.length);
  }

  const normalizedColumnCount = Math.max(2, Math.min(columnCount, headers.length));
  headers = headers.slice(0, normalizedColumnCount);
  const rows = splitLooseTableRows(afterSeparator, normalizedColumnCount);

  return { caption, headers, rows };
}

export function splitLooseTableRows(value: string, columnCount: number): string[][] {
  const body = String(value || '').trim();
  if (!body) return [];

  const collapsedRowSegments = body
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split(/\|\s+\|/g)
    .map((segment) => segment.trim())
    .filter(Boolean);

  if (collapsedRowSegments.length > 1) {
    return collapsedRowSegments
      .map((segment) => {
        const row = splitLooseTableCells(`| ${segment} |`).slice(0, columnCount);
        while (row.length < columnCount) row.push('');
        return row;
      })
      .filter((row) => row.some((cell) => cell.trim()));
  }

  const bodyCells = splitLooseTableCells(body).filter((cell) => cell.trim());
  const rows: string[][] = [];
  for (let index = 0; index < bodyCells.length; index += columnCount) {
    const row = bodyCells.slice(index, index + columnCount);
    while (row.length < columnCount) row.push('');
    if (row.some((cell) => cell.trim())) {
      rows.push(row);
    }
  }
  return rows;
}

export function formatMarkdownTable(table: LooseMarkdownTable): string {
  const escapeCell = (cell: string) => String(cell || '').replace(/\|/g, '\\|').trim();
  const headerLine = `| ${table.headers.map(escapeCell).join(' | ')} |`;
  const separatorLine = `| ${table.headers.map(() => '---').join(' | ')} |`;
  const rowLines = table.rows.map((row) => `| ${row.map(escapeCell).join(' | ')} |`);
  return [table.caption ? `**${escapeCell(table.caption)}**` : '', headerLine, separatorLine, ...rowLines]
    .filter(Boolean)
    .join('\n');
}

export function repairLooseMarkdownTables(markdown: string): string {
  return String(markdown || '')
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map((line) => {
      const table = parseLooseMarkdownTable(line);
      return table ? formatMarkdownTable(table) : line;
    })
    .join('\n');
}

export function cleanPageMarkdownForPreview(markdown: string): string {
  return String(markdown || '')
    .replace(/<\s*!?-{2,}\s*images?\s*-{2,}\s*>/gi, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

export function flattenReactText(node: React.ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(flattenReactText).join('');
  if (React.isValidElement(node)) return flattenReactText(node.props.children);
  return '';
}

export function DocumentMarkdownTable({ children }: React.ComponentPropsWithoutRef<'table'>) {
  return (
    <div className="not-prose my-3 max-h-[52vh] max-w-full overflow-auto rounded-xl border border-gray-200 bg-white shadow-sm">
      <table className="min-w-full border-collapse text-left text-xs text-oracle-dark-gray">
        {children}
      </table>
    </div>
  );
}

export function DocumentLooseTable({ table }: { table: LooseMarkdownTable }) {
  return (
    <>
      {table.caption ? (
        <p className="mb-2 mt-1 text-sm font-semibold text-oracle-dark-gray">{table.caption}</p>
      ) : null}
      <DocumentMarkdownTable>
        <thead className="sticky top-0 z-10 bg-gray-100">
          <tr>
            {table.headers.map((header, index) => (
              <th
                key={`${header}-${index}`}
                className="border border-gray-300 bg-gray-100 px-3 py-2 align-top font-semibold text-gray-800"
              >
                {header || `Column ${index + 1}`}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.length > 0 ? (
            table.rows.map((row, rowIndex) => (
              <tr key={`row-${rowIndex}`} className="odd:bg-white even:bg-gray-50/60">
                {table.headers.map((_, cellIndex) => (
                  <td
                    key={`cell-${rowIndex}-${cellIndex}`}
                    className="border border-gray-200 px-3 py-2 align-top leading-5 text-oracle-medium-gray"
                  >
                    {row[cellIndex] || ''}
                  </td>
                ))}
              </tr>
            ))
          ) : (
            <tr>
              <td
                colSpan={table.headers.length}
                className="border border-gray-200 px-3 py-3 text-sm text-oracle-light-gray"
              >
                No rows detected on this page.
              </td>
            </tr>
          )}
        </tbody>
      </DocumentMarkdownTable>
    </>
  );
}

export function DocumentMarkdownParagraph({ children }: React.ComponentPropsWithoutRef<'p'>) {
  const text = flattenReactText(children);
  const looseTable = parseLooseMarkdownTable(text);
  if (looseTable) {
    return <DocumentLooseTable table={looseTable} />;
  }
  return <p className="my-1.5 text-[13px] leading-5 text-oracle-dark-gray">{children}</p>;
}

export function DocumentMarkdownTh({ children }: React.ComponentPropsWithoutRef<'th'>) {
  return (
    <th className="border border-gray-300 bg-gray-100 px-3 py-2 align-top text-left font-semibold text-gray-800">
      {children}
    </th>
  );
}

export function DocumentMarkdownTd({ children }: React.ComponentPropsWithoutRef<'td'>) {
  return (
    <td className="border border-gray-200 px-3 py-2 align-top leading-5 text-oracle-medium-gray">
      {children}
    </td>
  );
}

export const DOCUMENT_MARKDOWN_COMPONENTS = {
  p: DocumentMarkdownParagraph,
  table: DocumentMarkdownTable,
  thead: ({ children }: React.ComponentPropsWithoutRef<'thead'>) => (
    <thead className="sticky top-0 z-10 bg-gray-100">{children}</thead>
  ),
  tbody: ({ children }: React.ComponentPropsWithoutRef<'tbody'>) => <tbody className="divide-y divide-gray-100">{children}</tbody>,
  tr: ({ children }: React.ComponentPropsWithoutRef<'tr'>) => <tr className="odd:bg-white even:bg-gray-50/60">{children}</tr>,
  th: DocumentMarkdownTh,
  td: DocumentMarkdownTd,
};

export function getDocumentDisplayParts(doc: any): { folder: string; fileName: string } {
  const fileName = String(doc?.original_name || doc?.filename || '').trim();
  if (!fileName) {
    return { folder: '', fileName: '-' };
  }
  const objectPath = String(doc?.file_output_obj_name || doc?.file_input_obj_name || '');
  const folder = extractFolderFromObjectPath(objectPath);
  if (!folder) {
    return { folder: '', fileName };
  }
  const normalizedFolder = normalizeComparableSegment(folder);
  const normalizedFileStem = normalizeComparableSegment(fileName);
  if (normalizedFolder && normalizedFolder === normalizedFileStem) {
    return { folder: '', fileName };
  }
  return { folder, fileName };
}

export function normalizeDocumentsPayload(payload: any): any[] {
  const rawItems = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.items)
    ? payload.items
    : [];
  return rawItems.map((item: any) => ({
    id: item?.id ?? item?.file_id,
    filename: item?.filename ?? item?.file_name ?? '',
    original_name: item?.original_name ?? item?.file_name ?? item?.filename ?? '',
    file_input_obj_name: item?.file_input_obj_name ?? '',
    file_output_obj_name: item?.file_output_obj_name ?? '',
    pages: item?.pages ?? item?.page_count ?? 0,
    status: normalizeStatus(item?.status),
    created_at: item?.created_at ?? item?.file_created ?? null,
    access_profiles:
      Array.isArray(item?.access_profiles) && item.access_profiles.length > 0
        ? item.access_profiles
        : item?.access_scope
        ? [String(item.access_scope)]
        : ['private'],
  }));
}

export function hasDocumentsInFlight(payload: any): boolean {
  return normalizeDocumentsPayload(payload).some((item: any) =>
    ['pending', 'processing_ocr'].includes(String(item?.status || ''))
  );
}

export function summarizeDocumentsQueue(documents: any[]): {
  pending: number;
  processing_ocr: number;
  error: number;
  completed: number;
} {
  return documents.reduce(
    (summary, item) => {
      const status = String(item?.status || '');
      if (status === 'pending') summary.pending += 1;
      else if (status === 'processing_ocr') summary.processing_ocr += 1;
      else if (status === 'error') summary.error += 1;
      else if (status === 'completed') summary.completed += 1;
      return summary;
    },
    {
      pending: 0,
      processing_ocr: 0,
      error: 0,
      completed: 0,
    }
  );
}

export function filterRagDocuments(documents: any[], statusFilter: string, searchTerm: string): any[] {
  const normalizedSearch = searchTerm.toLowerCase();
  return documents.filter((doc: any) => {
    if (statusFilter && String(doc?.status || '') !== statusFilter) {
      return false;
    }
    if (!normalizedSearch) return true;
    return (
      doc.filename?.toLowerCase().includes(normalizedSearch) ||
      doc.original_name?.toLowerCase().includes(normalizedSearch) ||
      getDocumentDisplayName(doc).toLowerCase().includes(normalizedSearch)
    );
  });
}

export function getSelectedRagDocuments(documents: any[], selectedDocumentIds: number[]): any[] {
  const selectedDocumentIdSet = new Set(selectedDocumentIds);
  return documents.filter((doc: any) => selectedDocumentIdSet.has(Number(doc.id)));
}

export function getSelectableDocumentIds(documents: any[]): number[] {
  return documents
    .map((doc: any) => Number(doc.id))
    .filter((docId) => Number.isFinite(docId) && docId > 0);
}

export function getAvailableDocumentIdsSignature(documents: any[]): string {
  return getSelectableDocumentIds(documents)
    .sort((left, right) => left - right)
    .join(',');
}

export function getPreparedItemKey(item: UploadPreparationItem): string {
  return `${item.group_source_path}::${item.source_path}`;
}

export function countEnabledPreparedItems(groups: UploadPreparationGroup[]): number {
  return groups.reduce(
    (total, group) => total + group.items.filter((item) => item.enabled).length,
    0
  );
}

export function countPreparedItems(groups: UploadPreparationGroup[]): number {
  return groups.reduce((total, group) => total + group.items.length, 0);
}

export function mergePreparedGroups(
  previousGroups: UploadPreparationGroup[],
  incomingGroups: UploadPreparationGroup[]
): UploadPreparationGroup[] {
  const orderedGroups = [...previousGroups];
  const indexesBySource = new Map<string, number>();
  orderedGroups.forEach((group, index) => {
    indexesBySource.set(group.group_source_path, index);
  });

  incomingGroups.forEach((group) => {
    const currentIndex = indexesBySource.get(group.group_source_path);
    if (currentIndex === undefined) {
      indexesBySource.set(group.group_source_path, orderedGroups.length);
      orderedGroups.push(group);
      return;
    }
    orderedGroups[currentIndex] = group;
  });

  return orderedGroups;
}

export function formatUploadGroupKind(kind: string): string {
  const normalizedKind = String(kind || '').trim().toLowerCase();
  if (!normalizedKind) {
    return 'Source';
  }
  if (normalizedKind === 'zip') {
    return 'ZIP';
  }
  if (normalizedKind === 'pdf') {
    return 'PDF';
  }
  return normalizedKind.charAt(0).toUpperCase() + normalizedKind.slice(1);
}

export function formatCountLabel(count: number, singular: string, plural?: string): string {
  const safeCount = Math.max(0, Number(count || 0));
  const label = safeCount === 1 ? singular : plural || `${singular}s`;
  return `${safeCount} ${label}`;
}

export type FilteredUploadDraftGroup = {
  group: UploadPreparationGroup;
  items: UploadPreparationItem[];
  groupMatches: boolean;
};

export function filterUploadDraftGroups(
  groups: UploadPreparationGroup[],
  uploadDraftFilter: string
): FilteredUploadDraftGroup[] {
  const normalizedFilter = uploadDraftFilter.trim().toLowerCase();
  if (!normalizedFilter) {
    return groups.map((group) => ({
      group,
      items: group.items,
      groupMatches: false,
    }));
  }

  return groups.reduce<FilteredUploadDraftGroup[]>((accumulator, group) => {
    const groupSearchText = [group.group_name, group.group_kind, group.archive_slug]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();
    const groupMatches = groupSearchText.includes(normalizedFilter);
    const items = groupMatches
      ? group.items
      : group.items.filter((item) =>
          [
            item.display_name,
            item.file_name,
            item.document_code,
            item.document_language,
            item.access,
          ]
            .filter(Boolean)
            .join(' ')
            .toLowerCase()
            .includes(normalizedFilter)
        );

    if (groupMatches || items.length > 0) {
      accumulator.push({
        group,
        items,
        groupMatches,
      });
    }
    return accumulator;
  }, []);
}

export function countMetadataMatchedPreparedItems(
  groups: UploadPreparationGroup[],
  metadataPreviewFileKeySet: Set<string>,
  hasMetadataSelection: boolean
): number {
  if (!hasMetadataSelection) return 0;
  return groups.reduce(
    (total, group) =>
      total +
      group.items.filter((item) =>
        metadataPreviewFileKeySet.has(normalizeMetadataFileKey(item.archive_slug))
      ).length,
    0
  );
}

export function buildPreparedUploadsSummary({
  isPreparing,
  hasPreparedUploads,
  totalPreparedItems,
  enabledPreparedItems,
  hasMetadataSelection,
  selectedMetadataLabel,
  metadataMatchedPreparedItems,
}: {
  isPreparing: boolean;
  hasPreparedUploads: boolean;
  totalPreparedItems: number;
  enabledPreparedItems: number;
  hasMetadataSelection: boolean;
  selectedMetadataLabel: string;
  metadataMatchedPreparedItems: number;
}): string {
  if (isPreparing) {
    return 'Preparing files...';
  }
  if (!hasPreparedUploads) {
    return `Select PDF or ZIP files to prepare the ingestion batch.${
      hasMetadataSelection ? ` Metadata: ${selectedMetadataLabel || 'selected'}` : ''
    }`;
  }
  return `${formatCountLabel(totalPreparedItems, 'file')} total \u00B7 ${enabledPreparedItems} selected${
    hasMetadataSelection
      ? ` \u00B7 metadata ${selectedMetadataLabel || 'selected'} (${metadataMatchedPreparedItems} matched)`
      : ''
  }`;
}

export function findDuplicatePreparedDocuments(
  documents: any[],
  enabledItems: UploadPreparationItem[]
): any[] {
  const duplicateById = new Map<string, any>();
  documents.forEach((document: any) => {
    const documentName = String(document.original_name || document.filename || '').trim().toLowerCase();
    if (!documentName) {
      return;
    }
    if (enabledItems.some((item) => item.file_name.toLowerCase() === documentName)) {
      duplicateById.set(String(document.id), document);
    }
  });
  return Array.from(duplicateById.values());
}

export function pruneSelectedDocumentIds(
  previousIds: number[],
  availableDocumentIds: Set<number>
): number[] {
  const nextIds = previousIds.filter((docId) => availableDocumentIds.has(docId));
  if (
    nextIds.length === previousIds.length &&
    nextIds.every((docId, index) => docId === previousIds[index])
  ) {
    return previousIds;
  }
  return nextIds;
}

export function toggleSelectedDocumentId(
  previousIds: number[],
  documentId: number,
  selected: boolean
): number[] {
  if (selected) {
    return previousIds.includes(documentId) ? previousIds : [...previousIds, documentId];
  }
  return previousIds.filter((currentId) => currentId !== documentId);
}

export function toggleVisibleDocumentIds(
  previousIds: number[],
  visibleDocumentIds: number[],
  selected: boolean
): number[] {
  const previousIdSet = new Set(previousIds);
  if (selected) {
    visibleDocumentIds.forEach((documentId) => previousIdSet.add(documentId));
  } else {
    visibleDocumentIds.forEach((documentId) => previousIdSet.delete(documentId));
  }
  return Array.from(previousIdSet);
}

export function cloneUploadDraftGroups(groups: UploadPreparationGroup[]): UploadPreparationGroup[] {
  return groups.map((group) => ({
    ...group,
    items: group.items.map((item) => ({ ...item })),
  }));
}

export function removeUploadDraftGroupBySource(
  groups: UploadPreparationGroup[],
  groupSourcePath: string
): UploadPreparationGroup[] {
  return groups.filter((group) => group.group_source_path !== groupSourcePath);
}

export function setUploadDraftGroupEnabled(
  groups: UploadPreparationGroup[],
  groupSourcePath: string,
  enabled: boolean
): UploadPreparationGroup[] {
  return groups.map((group) => {
    if (group.group_source_path !== groupSourcePath) {
      return group;
    }
    return {
      ...group,
      items: group.items.map((item) => ({ ...item, enabled })),
    };
  });
}

export function patchUploadDraftItem(
  groups: UploadPreparationGroup[],
  groupSourcePath: string,
  sourcePath: string,
  patch: Partial<UploadPreparationItem>
): UploadPreparationGroup[] {
  return groups.map((group) => {
    if (group.group_source_path !== groupSourcePath) {
      return group;
    }
    return {
      ...group,
      items: group.items.map((item) =>
        item.source_path === sourcePath ? { ...item, ...patch } : item
      ),
    };
  });
}

export const compactUploadDraftSelectClassName = 'input-oracle !h-7 !px-2 !py-0 !pr-7 !text-[11px] !leading-tight bg-white';
export const compactUploadDraftFieldLabelClassName = 'space-y-1 xl:space-y-0';
export const uploadDraftRowGridClassName =
  'flex flex-col gap-3 xl:grid xl:grid-cols-[minmax(0,1fr)_450px] xl:items-center xl:gap-3';
export const uploadDraftControlGridClassName =
  'grid gap-2 md:grid-cols-2 xl:w-[450px] xl:grid-cols-[112px_180px_140px]';
export const uploadDraftActionButtonClassName =
  'inline-flex h-10 shrink-0 cursor-pointer items-center justify-center gap-2 rounded border border-gray-300 bg-white px-3 text-sm font-medium text-gray-600 transition-colors hover:border-gray-400 hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oracle-red/35 disabled:cursor-not-allowed disabled:opacity-50';
export const uploadDraftMetadataSelectClassName =
  'h-10 min-w-[260px] shrink-0 rounded border border-gray-300 bg-white px-3 pr-9 text-sm font-medium text-gray-600 transition-colors hover:border-gray-400 hover:bg-gray-50 focus:border-oracle-red focus:outline-none focus:ring-2 focus:ring-oracle-red/35 disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-400 disabled:opacity-70';
export const documentToolbarButtonClassName =
  'flex h-10 shrink-0 items-center justify-center gap-2 rounded border border-gray-300 bg-white px-3 text-sm font-medium text-gray-600 transition-colors hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50';

export type UploadDraftMetadataMatchState = 'none' | 'matched' | 'unmatched' | 'loading';

export function normalizeMetadataFileKey(value: string): string {
  return String(value || '')
    .trim()
    .replace(/^\uFEFF/, '')
    .replace(/^['"]+|['"]+$/g, '')
    .replace(/\.(zip|pdf)$/i, '')
    .toLowerCase();
}

export function getUploadDraftMetadataMatchPresentation(matchState: UploadDraftMetadataMatchState): {
  label: string;
  className: string;
} {
  if (matchState === 'matched') {
    return {
      label: 'Matched',
      className: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    };
  }
  if (matchState === 'unmatched') {
    return {
      label: 'No match',
      className: 'border-amber-200 bg-amber-50 text-amber-800',
    };
  }
  if (matchState === 'loading') {
    return {
      label: 'Checking',
      className: 'border-gray-200 bg-gray-50 text-gray-600',
    };
  }
  return {
    label: 'No metadata',
    className: 'border-gray-200 bg-gray-50 text-oracle-medium-gray',
  };
}
