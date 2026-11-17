import { useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Layout } from '../common/Layout';
import { ConfirmDeleteModal } from '../common/ConfirmDeleteModal';
import { GlassModal } from '../common/GlassModal';
import { LoadingState } from '../common/LoadingState';
import { ModalPortal } from '../common/ModalPortal';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../context/ToastContext';
import { queryKeys } from '../../lib/queryClient';
import {
  type MetadataUploadDetailResponse,
  type MetadataUploadSummary,
} from '../../services/apiTypes';
import { metadataApi } from '../../services/metadataApi';

function normalizeStatus(value: string): 'active' | 'archived' {
  return String(value || '').toLowerCase() === 'archived' ? 'archived' : 'active';
}

function normalizeAccessScope(value: string | null | undefined): 'private' | 'all' {
  return String(value || '').toLowerCase() === 'all' ? 'all' : 'private';
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  const dd = String(date.getDate()).padStart(2, '0');
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const yyyy = date.getFullYear();
  const hh = String(date.getHours()).padStart(2, '0');
  const min = String(date.getMinutes()).padStart(2, '0');
  return `${dd}-${mm}-${yyyy} ${hh}:${min}`;
}

function formatCount(value: number | null | undefined): string {
  return new Intl.NumberFormat().format(Number(value || 0));
}

function getDatasetTitle(item: MetadataUploadSummary): string {
  return String(item.display_name || item.source_file_name || item.metadata_upload_id).trim();
}

function DeleteMetadataConfirmMessage({ dataset }: { dataset: MetadataUploadSummary }) {
  const name = getDatasetTitle(dataset) || 'this metadata dataset';
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

function getColumnPreview(columns: string[]): string {
  const visible = columns.slice(0, 4).join(', ');
  const remaining = Math.max(columns.length - 4, 0);
  return remaining > 0 ? `${visible} +${remaining}` : visible || '-';
}

function getMetadataPreviewCellValue(row: MetadataUploadDetailResponse['rows'][number], column: string): string {
  if (column === 'file') return String(row.file || '-');
  return String(row.fields?.[column] ?? '-');
}

function renderHighlightedText(value: string, searchTerm: string): ReactNode {
  const query = searchTerm.trim();
  if (!query) return value;

  const lowerValue = value.toLocaleLowerCase();
  const lowerQuery = query.toLocaleLowerCase();
  const parts: ReactNode[] = [];
  let cursor = 0;
  let matchIndex = lowerValue.indexOf(lowerQuery, cursor);

  while (matchIndex >= 0) {
    if (matchIndex > cursor) {
      parts.push(value.slice(cursor, matchIndex));
    }
    const nextCursor = matchIndex + query.length;
    parts.push(
      <mark key={`${matchIndex}-${nextCursor}`} className="rounded bg-yellow-200 px-0.5 text-oracle-dark-gray">
        {value.slice(matchIndex, nextCursor)}
      </mark>
    );
    cursor = nextCursor;
    matchIndex = lowerValue.indexOf(lowerQuery, cursor);
  }

  if (cursor < value.length) {
    parts.push(value.slice(cursor));
  }

  return parts.length > 0 ? parts : value;
}

const metadataActionButtonClassName =
  'inline-flex h-8 w-8 items-center justify-center rounded border border-gray-300 bg-white text-gray-600 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50';
const metadataDangerActionButtonClassName =
  'inline-flex h-8 w-8 items-center justify-center rounded border border-red-300 bg-white text-red-600 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50';
const metadataToolbarButtonClassName =
  'flex h-10 shrink-0 items-center justify-center gap-2 rounded border border-gray-300 bg-white px-3 text-sm font-medium text-gray-600 transition-colors hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50';
const metadataActiveStatusBadgeClassName =
  'inline-flex items-center rounded-xl border border-emerald-200 bg-emerald-50/60 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-emerald-700';
const metadataDisabledStatusBadgeClassName =
  'inline-flex items-center rounded-xl border border-gray-200 bg-gray-50 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-gray-700';
const metadataPrivateAccessBadgeClassName =
  'inline-flex items-center rounded-xl border border-gray-200 bg-gray-50 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-gray-700';
const metadataAllUsersAccessBadgeClassName =
  'inline-flex items-center rounded-xl border border-blue-200 bg-blue-50 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-blue-700';

function MetadataPreviewModal({
  detail,
  isLoading,
  onClose,
}: {
  detail?: MetadataUploadDetailResponse;
  isLoading: boolean;
  onClose: () => void;
}) {
  const pageSize = 10;
  const columns = detail?.columns || [];
  const visibleColumns = columns.length > 0 ? columns : ['file'];
  const rows = detail?.rows || [];
  const [previewSearch, setPreviewSearch] = useState('');
  const [previewPage, setPreviewPage] = useState(0);
  const normalizedSearch = previewSearch.trim().toLocaleLowerCase();
  const filteredRows = useMemo(() => {
    if (!normalizedSearch) return rows;
    return rows.filter((row) =>
      visibleColumns.some((column) =>
        getMetadataPreviewCellValue(row, column).toLocaleLowerCase().includes(normalizedSearch)
      )
    );
  }, [normalizedSearch, rows, visibleColumns]);
  const totalPages = Math.max(Math.ceil(filteredRows.length / pageSize), 1);
  const safePage = Math.min(previewPage, totalPages - 1);
  const startIndex = safePage * pageSize;
  const pageRows = filteredRows.slice(startIndex, startIndex + pageSize);
  const visibleStart = filteredRows.length === 0 ? 0 : startIndex + 1;
  const visibleEnd = Math.min(startIndex + pageSize, filteredRows.length);

  useEffect(() => {
    setPreviewPage(0);
  }, [normalizedSearch, detail?.metadata_upload_id]);

  return (
    <GlassModal
      open
      onClose={onClose}
      zIndex="z-[280]"
      containerClassName="items-start justify-center p-4"
      panelClassName="mt-12 w-full max-w-6xl border-0"
    >
        <div className="flex items-start gap-4 bg-oracle-dark-gray px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-semibold text-white">
              {detail ? getDatasetTitle(detail) : 'Metadata preview'}
            </h2>
            <p className="mt-1 text-sm text-gray-200">
              Table preview in CSV order. Showing {formatCount(pageSize)} row groups with searchable values.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-200 transition-colors hover:bg-white/10"
            aria-label="Close preview"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="space-y-3 p-4" style={{ background: 'rgba(255,255,255,0.75)' }}>
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
            <input
              type="text"
              value={previewSearch}
              onChange={(event) => setPreviewSearch(event.target.value)}
              className="input-oracle w-full"
              placeholder="Search metadata values..."
            />
            <div className="flex flex-wrap items-center gap-2 text-xs text-oracle-medium-gray">
              <span className="rounded-full border border-gray-200 bg-white px-3 py-1 font-semibold text-oracle-dark-gray">
                {formatCount(visibleColumns.length)} columns
              </span>
              <span className="rounded-full border border-gray-200 bg-white px-3 py-1">
                {formatCount(filteredRows.length)} of {formatCount(rows.length)} rows
              </span>
            </div>
          </div>

          <div className="rounded-xl border border-white/30 bg-white/70">
          {isLoading ? (
            <LoadingState className="py-12" />
          ) : !detail ? (
            <div className="p-8 text-center text-sm text-oracle-medium-gray">
              Could not load metadata preview.
            </div>
          ) : rows.length === 0 ? (
            <div className="p-8 text-center text-sm text-oracle-medium-gray">
              No preview rows are available for this dataset.
            </div>
          ) : filteredRows.length === 0 ? (
            <div className="p-8 text-center text-sm text-oracle-medium-gray">
              No metadata rows match "{previewSearch}".
            </div>
          ) : (
            <>
              <div className="max-h-[58vh] overflow-auto">
                <table className="min-w-max divide-y divide-gray-200 text-left">
                  <thead className="sticky top-0 z-10 bg-gray-50">
                    <tr>
                      {visibleColumns.map((column, columnIndex) => (
                        <th
                          key={column}
                          className={`whitespace-nowrap px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500 ${
                            columnIndex === 0 ? 'sticky left-0 z-20 min-w-[180px] bg-gray-50 shadow-[1px_0_0_#e5e7eb]' : 'min-w-[150px]'
                          }`}
                        >
                          {column}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 bg-white">
                    {pageRows.map((row, rowIndex) => (
                      <tr key={`${row.file}-${startIndex + rowIndex}`} className="hover:bg-gray-50">
                        {visibleColumns.map((column, columnIndex) => {
                          const value = getMetadataPreviewCellValue(row, column);
                          return (
                            <td
                              key={`${row.file}-${column}`}
                              className={`max-w-[260px] px-3 py-2 align-top text-xs text-oracle-dark-gray ${
                                columnIndex === 0
                                  ? 'sticky left-0 z-10 bg-white font-semibold shadow-[1px_0_0_#e5e7eb]'
                                  : ''
                              }`}
                              title={`${column}: ${value}`}
                            >
                              <span className="line-clamp-2 break-words">
                                {renderHighlightedText(value, previewSearch)}
                              </span>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex flex-col gap-2 border-t border-gray-200 bg-white/80 px-3 py-2 text-xs text-oracle-medium-gray sm:flex-row sm:items-center sm:justify-between">
                <span>
                  Showing {formatCount(visibleStart)}-{formatCount(visibleEnd)} of{' '}
                  {formatCount(filteredRows.length)} row(s)
                </span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setPreviewPage((page) => Math.max(page - 1, 0))}
                    disabled={safePage === 0}
                    className="rounded border border-gray-300 bg-white px-3 py-1 font-medium text-gray-600 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Previous
                  </button>
                  <span className="min-w-[76px] text-center">
                    Page {formatCount(safePage + 1)} / {formatCount(totalPages)}
                  </span>
                  <button
                    type="button"
                    onClick={() => setPreviewPage((page) => Math.min(page + 1, totalPages - 1))}
                    disabled={safePage >= totalPages - 1}
                    className="rounded border border-gray-300 bg-white px-3 py-1 font-medium text-gray-600 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
          </div>
        </div>
    </GlassModal>
  );
}

export function Metadata() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const sessionScope = user?.user_id ?? 'anonymous';
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const replaceInputRef = useRef<HTMLInputElement | null>(null);

  const [searchTerm, setSearchTerm] = useState('');
  const [metadataStatusFilter, setMetadataStatusFilter] = useState<'active' | 'archived' | 'all'>('active');
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [replaceTarget, setReplaceTarget] = useState<MetadataUploadSummary | null>(null);
  const [editingDataset, setEditingDataset] = useState<MetadataUploadSummary | null>(null);
  const [editDisplayName, setEditDisplayName] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editMetadataStatus, setEditMetadataStatus] = useState<'active' | 'archived'>('active');
  const [editAccessScope, setEditAccessScope] = useState<'private' | 'all'>('private');
  const [newMetadataAccess, setNewMetadataAccess] = useState<'private' | 'all'>('private');
  const [deleteTarget, setDeleteTarget] = useState<MetadataUploadSummary | null>(null);

  const uploadsQuery = useQuery({
    queryKey: queryKeys.metadata.uploads(sessionScope),
    queryFn: () =>
      metadataApi
        .listUploads({ includeArchived: true })
        .then((response) => response.data.items || []),
  });

  const previewQuery = useQuery({
    queryKey: previewId ? queryKeys.metadata.detail(sessionScope, previewId) : ['metadata-upload-detail', sessionScope, 'none'],
    queryFn: () => metadataApi.getUpload(previewId || '', 100).then((response) => response.data),
    enabled: Boolean(previewId),
  });

  const datasets = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    return (uploadsQuery.data || [])
      .filter((item) => metadataStatusFilter === 'all' || normalizeStatus(item.metadata_status) === metadataStatusFilter)
      .filter((item) => {
        if (!term) return true;
        return [
          item.display_name,
          item.source_file_name,
          item.description,
          item.metadata_upload_id,
          ...(item.columns || []),
        ]
          .join(' ')
          .toLowerCase()
          .includes(term);
      });
  }, [metadataStatusFilter, searchTerm, uploadsQuery.data]);

  const invalidateMetadata = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.metadata.uploads(sessionScope) });
  };

  const uploadMutation = useMutation({
    mutationFn: ({ file, accessScope }: { file: File; accessScope: 'private' | 'all' }) =>
      metadataApi.uploadCsv(file, undefined, undefined, accessScope),
    onSuccess: (response) => {
      invalidateMetadata();
      showToast(`Metadata loaded: ${response.data.source_file_name}`, 'success');
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error?.message || 'Failed to upload metadata', 'error');
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({
      dataset,
      displayName,
      description,
      metadataStatus,
      accessScope,
    }: {
      dataset: MetadataUploadSummary;
      displayName?: string | null;
      description?: string | null;
      metadataStatus?: 'active' | 'archived';
      accessScope?: 'private' | 'all';
    }) =>
      metadataApi.updateUpload(dataset.metadata_upload_id, {
        ...(displayName !== undefined ? { display_name: displayName } : {}),
        ...(description !== undefined ? { description } : {}),
        ...(metadataStatus ? { metadata_status: metadataStatus } : {}),
        ...(accessScope ? { access_scope: accessScope } : {}),
      }),
    onSuccess: () => {
      invalidateMetadata();
      setEditingDataset(null);
      showToast('Metadata dataset updated', 'success');
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error?.message || 'Failed to update metadata', 'error');
    },
  });

  const replaceMutation = useMutation({
    mutationFn: ({ dataset, file }: { dataset: MetadataUploadSummary; file: File }) =>
      metadataApi.replaceCsv(dataset.metadata_upload_id, file),
    onSuccess: (response) => {
      invalidateMetadata();
      if (replaceTarget) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.metadata.detail(sessionScope, replaceTarget.metadata_upload_id),
        });
      }
      setReplaceTarget(null);
      showToast(`Metadata replaced: ${response.data.source_file_name}`, 'success');
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error?.message || 'Failed to replace metadata', 'error');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (dataset: MetadataUploadSummary) => metadataApi.deleteUpload(dataset.metadata_upload_id),
    onSuccess: () => {
      invalidateMetadata();
      setDeleteTarget(null);
      showToast('Metadata dataset deleted', 'success');
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error?.message || 'Failed to delete metadata', 'error');
    },
  });

  const handleUploadSelect = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0] || null;
    event.currentTarget.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.csv')) {
      showToast('Only CSV files are supported', 'error');
      return;
    }
    uploadMutation.mutate({ file, accessScope: newMetadataAccess });
  };

  const handleReplaceSelect = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0] || null;
    event.currentTarget.value = '';
    if (!file || !replaceTarget) return;
    if (!file.name.toLowerCase().endsWith('.csv')) {
      showToast('Only CSV files are supported', 'error');
      return;
    }
    replaceMutation.mutate({ dataset: replaceTarget, file });
  };

  const openEditModal = (dataset: MetadataUploadSummary) => {
    setEditingDataset(dataset);
    setEditDisplayName(getDatasetTitle(dataset));
    setEditDescription(dataset.description || '');
    setEditMetadataStatus(normalizeStatus(dataset.metadata_status));
    setEditAccessScope(normalizeAccessScope(dataset.access_scope));
  };

  const isMutating =
    uploadMutation.isPending ||
    updateMutation.isPending ||
    replaceMutation.isPending ||
    deleteMutation.isPending;

  return (
    <Layout>
      <div className="space-y-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Metadata</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-oracle-medium-gray">
              Manage CSV metadata datasets used to route RAG questions and link logical files with their documents.
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => uploadInputRef.current?.click()}
              disabled={isMutating}
              className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg border border-transparent bg-oracle-red px-4 text-sm font-medium text-white transition-colors hover:bg-oracle-red/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Metadata CSV
            </button>
          </div>
        </div>

        <input
          ref={uploadInputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={handleUploadSelect}
        />
        <input
          ref={replaceInputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={handleReplaceSelect}
        />

        <div className="app-light-surface rounded-lg bg-white p-6 shadow">
          <div className="mb-5 flex flex-col gap-3 xl:flex-row xl:items-center">
            <div className="grid flex-1 grid-cols-1 gap-3 md:grid-cols-[1fr_150px_150px]">
              <input
                type="text"
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                className="input-oracle"
                placeholder="Search by dataset, source file or column..."
              />
              <select
                value={metadataStatusFilter}
                onChange={(event) => setMetadataStatusFilter(event.target.value as 'active' | 'archived' | 'all')}
                className="input-oracle"
                aria-label="Filter metadata status"
              >
                <option value="all">All statuses</option>
                <option value="active">Active</option>
                <option value="archived">Archived</option>
              </select>
              <select
                value={newMetadataAccess}
                onChange={(event) => setNewMetadataAccess(event.target.value as 'private' | 'all')}
                className="input-oracle"
                aria-label="New metadata access"
                disabled={isMutating}
                title="New metadata access"
              >
                <option value="private">Private</option>
                <option value="all">All Users</option>
              </select>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => uploadsQuery.refetch()}
                disabled={uploadsQuery.isFetching}
                title="Refresh"
                className={`${metadataToolbarButtonClassName} w-10 px-0`}
                aria-label="Refresh"
              >
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </button>
            </div>
          </div>

          {uploadsQuery.isLoading ? (
            <LoadingState className="py-12" />
          ) : uploadsQuery.isError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-800">
              Could not load metadata datasets.
            </div>
          ) : datasets.length === 0 ? (
            <div className="rounded-lg border-2 border-dashed border-gray-300 bg-gray-50 p-10 text-center">
              <p className="text-sm font-medium text-oracle-dark-gray">No metadata datasets found</p>
              <p className="mt-1 text-sm text-oracle-medium-gray">
                Upload a CSV with first column <code>file</code> to start routing questions with metadata.
              </p>
              <button
                type="button"
                onClick={() => uploadInputRef.current?.click()}
                className="mt-4 text-sm font-medium text-oracle-blue-link hover:underline"
              >
                Upload metadata CSV
              </button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Dataset
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Rows
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Columns
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Coverage
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Updated
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Access
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Status
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {datasets.map((dataset) => {
                    const status = normalizeStatus(dataset.metadata_status);
                    const accessScope = normalizeAccessScope(dataset.access_scope);
                    const currentUserId = Number(user?.user_id ?? -1);
                    const canManageDataset = Number(dataset.owner_user_id ?? -1) === currentUserId;
                    return (
                      <tr key={dataset.metadata_upload_id} className="hover:bg-gray-50">
                        <td className="max-w-[320px] px-5 py-4">
                          <p className="truncate text-sm font-semibold text-oracle-dark-gray" title={getDatasetTitle(dataset)}>
                            {getDatasetTitle(dataset)}
                          </p>
                        </td>
                        <td className="whitespace-nowrap px-4 py-4 text-sm text-oracle-dark-gray">
                          {formatCount(dataset.row_count || dataset.total_rows)}
                        </td>
                        <td className="max-w-[330px] px-4 py-4">
                          <p
                            className="truncate text-sm text-oracle-dark-gray"
                            title={(dataset.columns || []).join(', ')}
                          >
                            <span className="font-semibold">{formatCount(dataset.columns.length)}</span>{' '}
                            <span className="text-oracle-medium-gray">({getColumnPreview(dataset.columns || [])})</span>
                          </p>
                        </td>
                        <td className="whitespace-nowrap px-4 py-4 text-sm text-oracle-dark-gray">
                          <span title="Metadata rows matching logical files">
                            {formatCount(dataset.matched_files_count)} matched
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-4 py-4 text-sm text-oracle-medium-gray">
                          {formatDate(dataset.updated_at || dataset.created_at)}
                        </td>
                        <td className="px-4 py-4">
                          <span
                            className={
                              accessScope === 'all'
                                ? metadataAllUsersAccessBadgeClassName
                                : metadataPrivateAccessBadgeClassName
                            }
                          >
                            {accessScope === 'all' ? 'All Users' : 'Private'}
                          </span>
                        </td>
                        <td className="px-4 py-4">
                          <span
                            className={
                              status === 'active'
                                ? metadataActiveStatusBadgeClassName
                                : metadataDisabledStatusBadgeClassName
                            }
                          >
                            {status}
                          </span>
                        </td>
                        <td className="px-4 py-4 text-right">
                          <div className="inline-flex justify-end gap-1">
                            <button
                              type="button"
                              onClick={() => setPreviewId(dataset.metadata_upload_id)}
                              className={metadataActionButtonClassName}
                              title="Preview"
                              aria-label="Preview metadata"
                            >
                              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                              </svg>
                              <span className="sr-only">Preview</span>
                            </button>
                            <button
                              type="button"
                              onClick={() => openEditModal(dataset)}
                              className={metadataActionButtonClassName}
                              disabled={!canManageDataset}
                              title="Edit"
                              aria-label="Edit metadata"
                            >
                              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                              </svg>
                              <span className="sr-only">Edit</span>
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setReplaceTarget(dataset);
                                replaceInputRef.current?.click();
                              }}
                              className={metadataActionButtonClassName}
                              disabled={!canManageDataset}
                              title="Replace"
                              aria-label="Replace metadata CSV"
                            >
                              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16.5V18a2 2 0 002 2h12a2 2 0 002-2v-1.5M8 9l4-4m0 0l4 4m-4-4v11" />
                              </svg>
                              <span className="sr-only">Replace</span>
                            </button>
                            <button
                              type="button"
                              onClick={() => setDeleteTarget(dataset)}
                              className={metadataDangerActionButtonClassName}
                              disabled={!canManageDataset}
                              title="Delete"
                              aria-label="Delete metadata"
                            >
                              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                              </svg>
                              <span className="sr-only">Delete</span>
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {previewId ? (
        <MetadataPreviewModal
          detail={previewQuery.data}
          isLoading={previewQuery.isLoading || previewQuery.isFetching}
          onClose={() => setPreviewId(null)}
        />
      ) : null}

      {editingDataset ? (
        <ModalPortal zIndex="z-[280]" onBackdropClick={() => setEditingDataset(null)}>
          <div
            className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 className="text-lg font-semibold text-oracle-dark-gray">Edit metadata dataset</h2>
            <div className="mt-5 space-y-4">
              <label className="block">
                <span className="text-sm font-medium text-oracle-dark-gray">Display name</span>
                <input
                  type="text"
                  value={editDisplayName}
                  onChange={(event) => setEditDisplayName(event.target.value)}
                  className="input-oracle mt-1"
                />
              </label>
              <label className="block">
                <span className="text-sm font-medium text-oracle-dark-gray">Description</span>
                <textarea
                  value={editDescription}
                  onChange={(event) => setEditDescription(event.target.value)}
                  rows={4}
                  className="input-oracle mt-1 resize-y"
                />
              </label>
              <label className="block">
                <span className="text-sm font-medium text-oracle-dark-gray">Access</span>
                <select
                  value={editAccessScope}
                  onChange={(event) => setEditAccessScope(event.target.value as 'private' | 'all')}
                  className="input-oracle mt-1"
                >
                  <option value="private">Private</option>
                  <option value="all">All Users</option>
                </select>
                <p className="mt-1 text-xs leading-5 text-oracle-medium-gray">
                  All Users metadata can be selected by other users when loading documents.
                </p>
              </label>
              <label className="block">
                <span className="text-sm font-medium text-oracle-dark-gray">Status</span>
                <select
                  value={editMetadataStatus}
                  onChange={(event) => setEditMetadataStatus(event.target.value as 'active' | 'archived')}
                  className="input-oracle mt-1"
                >
                  <option value="active">Active</option>
                  <option value="archived">Archived</option>
                </select>
                <p className="mt-1 text-xs leading-5 text-oracle-medium-gray">
                  Archived datasets are visible when the status filter is set to Archived or All statuses.
                </p>
              </label>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button type="button" onClick={() => setEditingDataset(null)} className="btn-secondary">
                Cancel
              </button>
              <button
                type="button"
                onClick={() =>
                  updateMutation.mutate({
                    dataset: editingDataset,
                    displayName: editDisplayName,
                    description: editDescription,
                    metadataStatus: editMetadataStatus,
                    accessScope: editAccessScope,
                  })
                }
                disabled={updateMutation.isPending}
                className="btn-primary"
              >
                Save
              </button>
            </div>
          </div>
        </ModalPortal>
      ) : null}

      {deleteTarget ? (
        <ConfirmDeleteModal
          title="Delete metadata dataset"
          message={<DeleteMetadataConfirmMessage dataset={deleteTarget} />}
          detail="This removes the CSV catalog entry and its rows. Linked document metadata will lose this dataset reference."
          loading={deleteMutation.isPending}
          onConfirm={() => deleteMutation.mutate(deleteTarget)}
          onCancel={() => setDeleteTarget(null)}
        />
      ) : null}
    </Layout>
  );
}
