import type { ReactNode } from 'react';

import type { UploadPreparationItem } from '../../services/apiTypes';
import {
  ACCESS_OPTIONS,
  compactUploadDraftFieldLabelClassName,
  compactUploadDraftSelectClassName,
  DEFAULT_UPLOAD_ACCESS,
  DEFAULT_UPLOAD_LANGUAGE,
  type FilteredUploadDraftGroup,
  formatUploadGroupKind,
  getPreparedItemKey,
  getUploadDraftMetadataMatchPresentation,
  LANGUAGE_OPTIONS,
  uploadDraftControlGridClassName,
  uploadDraftRowGridClassName,
  type UploadDraftMetadataMatchState,
} from './RAG.model';

type RAGUploadDraftListProps = {
  filteredUploadDraftGroups: FilteredUploadDraftGroup[];
  uploadDraftFilter: string;
  hasUploadDraftFilter: boolean;
  collapsedUploadGroups: Record<string, boolean>;
  onToggleGroup: (groupSourcePath: string) => void;
  onRemoveGroup: (groupSourcePath: string) => void;
  onSetGroupEnabled: (groupSourcePath: string, enabled: boolean) => void;
  onUpdateItem: (
    groupSourcePath: string,
    sourcePath: string,
    patch: Partial<UploadPreparationItem>
  ) => void;
  getMetadataMatchState: (archiveSlug: string) => UploadDraftMetadataMatchState;
};

function highlightText(text: string | undefined, search: string): ReactNode {
  if (!text || !search) return text || '-';
  const index = text.toLowerCase().indexOf(search.toLowerCase());
  if (index === -1) return text;
  return (
    <>
      {text.slice(0, index)}
      <span className="bg-yellow-200 px-0.5 rounded">{text.slice(index, index + search.length)}</span>
      {text.slice(index + search.length)}
    </>
  );
}

function UploadDraftMetadataBadge({
  archiveSlug,
  getMetadataMatchState,
}: {
  archiveSlug: string;
  getMetadataMatchState: (archiveSlug: string) => UploadDraftMetadataMatchState;
}) {
  const metadataMatchState = getMetadataMatchState(archiveSlug);
  const metadataMatchPresentation = getUploadDraftMetadataMatchPresentation(metadataMatchState);
  const metadataMatchTitle =
    metadataMatchState === 'matched'
      ? `Matched metadata row for ${archiveSlug}`
      : metadataMatchState === 'unmatched'
      ? `No metadata row matched ${archiveSlug}`
      : metadataMatchState === 'loading'
      ? 'Loading metadata preview rows'
      : 'Add or select metadata to preview matches';

  return (
    <span
      className={`inline-flex h-7 w-full items-center justify-center rounded-md border px-2 text-[11px] font-medium ${metadataMatchPresentation.className}`}
      title={metadataMatchTitle}
    >
      {metadataMatchPresentation.label}
    </span>
  );
}

export function RAGUploadDraftList({
  filteredUploadDraftGroups,
  uploadDraftFilter,
  hasUploadDraftFilter,
  collapsedUploadGroups,
  onToggleGroup,
  onRemoveGroup,
  onSetGroupEnabled,
  onUpdateItem,
  getMetadataMatchState,
}: RAGUploadDraftListProps) {
  return (
    <>
      {filteredUploadDraftGroups.length > 0 && (
        <div className="hidden xl:grid grid-cols-[minmax(0,1fr)_450px] items-end gap-3 border-b border-gray-100 bg-gray-50 px-4 py-2 pl-16">
          <div />
          <div className={uploadDraftControlGridClassName}>
            <span className="text-[11px] font-semibold uppercase tracking-wide text-oracle-medium-gray">
              Metadata
            </span>
            <span className="text-[11px] font-semibold uppercase tracking-wide text-oracle-medium-gray">
              Language
            </span>
            <span className="text-[11px] font-semibold uppercase tracking-wide text-oracle-medium-gray">
              Access
            </span>
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {filteredUploadDraftGroups.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-oracle-medium-gray">
            No prepared files match this filter.
          </div>
        ) : (
          filteredUploadDraftGroups.map(({ group, items, groupMatches }, groupIndex) => {
            const totalGroupItems = group.items.length;
            const enabledGroupItems = group.items.filter((item) => item.enabled).length;
            const isGroupCollapsed =
              hasUploadDraftFilter ? false : Boolean(collapsedUploadGroups[group.group_source_path]);
            const isGroupChecked = totalGroupItems > 0 && enabledGroupItems === totalGroupItems;

            return (
              <div
                key={group.group_source_path}
                className={groupIndex > 0 ? 'border-t border-gray-200' : ''}
              >
                <div className="flex items-center gap-3 px-4 py-1">
                  <button
                    type="button"
                    onClick={() => onToggleGroup(group.group_source_path)}
                    className="inline-flex h-6 w-6 items-center justify-center rounded-md text-oracle-medium-gray transition-colors hover:bg-gray-100"
                    aria-label={isGroupCollapsed ? 'Expand group' : 'Collapse group'}
                  >
                    <svg
                      className={`h-4 w-4 transition-transform ${
                        isGroupCollapsed ? '-rotate-90' : 'rotate-0'
                      }`}
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>

                  <input
                    type="checkbox"
                    checked={isGroupChecked}
                    onChange={(event) =>
                      onSetGroupEnabled(group.group_source_path, event.target.checked)
                    }
                    className="h-4 w-4 rounded border-gray-300 text-oracle-red accent-oracle-red focus:ring-oracle-red"
                  />

                  <span className="text-oracle-medium-gray">
                    <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"
                      />
                    </svg>
                  </span>

                  <button
                    type="button"
                    onClick={() => onToggleGroup(group.group_source_path)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-semibold text-oracle-dark-gray">
                        {highlightText(group.group_name, uploadDraftFilter)}
                      </span>
                      <span className="inline-flex items-center rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-oracle-medium-gray">
                        {formatUploadGroupKind(group.group_kind)}
                      </span>
                      {groupMatches && hasUploadDraftFilter && (
                        <span className="inline-flex items-center rounded-full bg-yellow-100 px-2 py-0.5 text-[10px] font-medium text-yellow-800">
                          Match
                        </span>
                      )}
                    </div>
                  </button>

                  <span className="shrink-0 text-xs font-medium text-oracle-medium-gray">
                    {enabledGroupItems}/{totalGroupItems} selected
                  </span>

                  <button
                    type="button"
                    onClick={() => onRemoveGroup(group.group_source_path)}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-red-200 text-red-600 transition-colors hover:bg-red-50"
                    aria-label="Remove source"
                  >
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                      />
                    </svg>
                  </button>
                </div>

                {!isGroupCollapsed && (
                  <>
                    {items.map((item) => (
                      <div
                        key={getPreparedItemKey(item)}
                        className={`border-t ${
                          item.enabled ? 'border-gray-100 bg-white' : 'border-gray-100 bg-gray-50/70'
                        }`}
                      >
                        <div className="px-4 py-1 pl-16">
                          <div className={uploadDraftRowGridClassName}>
                            <div className="flex min-w-0 items-start gap-3 xl:items-center">
                              <input
                                type="checkbox"
                                checked={item.enabled}
                                onChange={(event) =>
                                  onUpdateItem(group.group_source_path, item.source_path, {
                                    enabled: event.target.checked,
                                  })
                                }
                                className="h-4 w-4 rounded border-gray-300 text-oracle-red accent-oracle-red focus:ring-oracle-red"
                              />

                              <span className="text-oracle-medium-gray">
                                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M7 3h7l5 5v13a1 1 0 01-1 1H7a2 2 0 01-2-2V5a2 2 0 012-2z"
                                  />
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 3v5h5" />
                                </svg>
                              </span>

                              <div className="min-w-0 flex-1">
                                <div className="min-w-0">
                                  <p
                                    className="truncate text-sm font-medium text-oracle-dark-gray"
                                    title={item.display_name || item.file_name}
                                  >
                                    {highlightText(item.display_name || item.file_name, uploadDraftFilter)}
                                  </p>
                                </div>
                                {item.display_name !== item.file_name && (
                                  <p
                                    className="mt-1 truncate text-xs text-oracle-medium-gray"
                                    title={item.file_name}
                                  >
                                    {highlightText(item.file_name, uploadDraftFilter)}
                                  </p>
                                )}
                              </div>
                            </div>

                            <div className={uploadDraftControlGridClassName}>
                              <div className={compactUploadDraftFieldLabelClassName}>
                                <span className="text-[11px] font-semibold uppercase tracking-wide text-oracle-medium-gray xl:hidden">
                                  Metadata
                                </span>
                                <UploadDraftMetadataBadge
                                  archiveSlug={item.archive_slug}
                                  getMetadataMatchState={getMetadataMatchState}
                                />
                              </div>
                              <label className={compactUploadDraftFieldLabelClassName}>
                                <span className="text-[11px] font-semibold uppercase tracking-wide text-oracle-medium-gray xl:hidden">
                                  Language
                                </span>
                                <select
                                  value={item.document_language || DEFAULT_UPLOAD_LANGUAGE}
                                  onChange={(event) =>
                                    onUpdateItem(group.group_source_path, item.source_path, {
                                      document_language: event.target.value,
                                    })
                                  }
                                  className={`${compactUploadDraftSelectClassName} w-full`}
                                >
                                  {LANGUAGE_OPTIONS.map((option) => (
                                    <option key={option.value} value={option.value}>
                                      {option.label}
                                    </option>
                                  ))}
                                </select>
                              </label>
                              <label className={compactUploadDraftFieldLabelClassName}>
                                <span className="text-[11px] font-semibold uppercase tracking-wide text-oracle-medium-gray xl:hidden">
                                  Access
                                </span>
                                <select
                                  value={item.access || DEFAULT_UPLOAD_ACCESS}
                                  onChange={(event) =>
                                    onUpdateItem(group.group_source_path, item.source_path, {
                                      access: event.target.value,
                                    })
                                  }
                                  className={`${compactUploadDraftSelectClassName} w-full`}
                                >
                                  {ACCESS_OPTIONS.map((option) => (
                                    <option key={option.value} value={option.value}>
                                      {option.label}
                                    </option>
                                  ))}
                                </select>
                              </label>
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </>
                )}
              </div>
            );
          })
        )}
      </div>
    </>
  );
}
