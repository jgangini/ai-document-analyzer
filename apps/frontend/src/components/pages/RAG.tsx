import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Layout } from '../common/Layout';
import { ConfirmDeleteModal } from '../common/ConfirmDeleteModal';
import { queryKeys } from '../../lib/queryClient';
import {
  type MetadataUploadSummary,
  type UploadPreparationGroup,
  type UploadPreparationItem,
} from '../../services/apiTypes';
import { metadataApi } from '../../services/metadataApi';
import { ragApi } from '../../services/ragApi';
import { useToast } from '../../context/ToastContext';
import { useAuth } from '../../context/AuthContext';
import {
  buildPreparedUploadsSummary,
  cloneUploadDraftGroups,
  countMetadataMatchedPreparedItems,
  countEnabledPreparedItems,
  countPreparedItems,
  DEFAULT_UPLOAD_ACCESS,
  DEFAULT_UPLOAD_LANGUAGE,
  DeleteDocumentConfirmMessage,
  filterRagDocuments,
  filterUploadDraftGroups,
  findDuplicatePreparedDocuments,
  getAvailableDocumentIdsSignature,
  getDocumentDisplayName,
  getSelectableDocumentIds,
  getSelectedRagDocuments,
  hasDocumentsInFlight,
  ITEMS_PER_PAGE,
  mergePreparedGroups,
  normalizeDocumentsPayload,
  normalizeMetadataFileKey,
  patchUploadDraftItem,
  pruneSelectedDocumentIds,
  removeUploadDraftGroupBySource,
  setUploadDraftGroupEnabled,
  summarizeDocumentsQueue,
  toggleSelectedDocumentId,
  toggleVisibleDocumentIds,
} from './RAG.model';
import type {
  UploadDraftMetadataMatchState,
} from './RAG.model';
import { DocumentViewerModal } from './RAGDocumentViewerModal';
import { RAGDocumentTable } from './RAGDocumentTable';
import { EditDocumentModal } from './RAGEditDocumentModal';
import { RAGQueueSummary } from './RAGQueueSummary';
import { RAGReplaceConfirmModal } from './RAGReplaceConfirmModal';
import { RAGToolbar } from './RAGToolbar';
import { RAGUploadDraftList } from './RAGUploadDraftList';
import { RAGUploadModal } from './RAGUploadModal';

export function RAG() {
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [searchTerm, setSearchTerm] = useState('');
  const [uploadDraftFilter, setUploadDraftFilter] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  const [viewingDoc, setViewingDoc] = useState<any>(null);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadDraftGroups, setUploadDraftGroups] = useState<UploadPreparationGroup[]>([]);
  const [selectedMetadataUploadId, setSelectedMetadataUploadId] = useState('');
  const [metadataPreviewFileKeys, setMetadataPreviewFileKeys] = useState<string[]>([]);
  const [collapsedUploadGroups, setCollapsedUploadGroups] = useState<Record<string, boolean>>({});
  const [editingDocs, setEditingDocs] = useState<any[] | null>(null);
  const [deletingDocs, setDeletingDocs] = useState<any[] | null>(null);
  const [replaceConfirm, setReplaceConfirm] = useState<{
    duplicateDocs: any[];
    groups: UploadPreparationGroup[];
  } | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<number[]>([]);
  const selectAllDocumentsRef = useRef<HTMLInputElement | null>(null);
  const { showToast } = useToast();
  const { isAdmin, user } = useAuth();
  const queryClient = useQueryClient();
  const sessionScope = user?.user_id ?? 'anonymous';

  const { data: documentsData, isLoading } = useQuery({
    queryKey: queryKeys.rag.documents(sessionScope),
    queryFn: () => ragApi.listDocuments(),
    refetchInterval: (query) =>
      hasDocumentsInFlight((query.state.data as any)?.data) ? 5000 : false,
  });

  const metadataUploadsQuery = useQuery({
    queryKey: queryKeys.metadata.uploads(sessionScope),
    queryFn: () =>
      metadataApi
        .listUploads({ includeArchived: false })
        .then((response) => response.data.items || []),
    enabled: showUploadModal,
  });

  const selectedMetadataUpload = useMemo(
    () =>
      (metadataUploadsQuery.data || []).find(
        (item: MetadataUploadSummary) => item.metadata_upload_id === selectedMetadataUploadId
      ) || null,
    [metadataUploadsQuery.data, selectedMetadataUploadId]
  );

  const selectedMetadataDetailQuery = useQuery({
    queryKey: selectedMetadataUploadId
      ? queryKeys.metadata.detail(sessionScope, selectedMetadataUploadId)
      : ['metadata-upload-detail', sessionScope, 'none'],
    queryFn: () =>
      metadataApi.getUpload(selectedMetadataUploadId, 1000).then((response) => response.data),
    enabled: showUploadModal && Boolean(selectedMetadataUploadId),
  });

  const prepareUploadMutation = useMutation({
    mutationFn: (files: File[]) =>
      ragApi.prepareUploadPlan(files, DEFAULT_UPLOAD_ACCESS, DEFAULT_UPLOAD_LANGUAGE),
    onSuccess: (response) => {
      const groups = Array.isArray(response?.data?.groups) ? response.data.groups : [];
      const errors = Array.isArray(response?.data?.errors) ? response.data.errors : [];
      if (groups.length > 0) {
        setUploadDraftGroups((previousGroups) => mergePreparedGroups(previousGroups, groups));
        setCollapsedUploadGroups((previousGroups) => {
          const nextGroups = { ...previousGroups };
          groups.forEach((group) => {
            nextGroups[group.group_source_path] = true;
          });
          return nextGroups;
        });
        showToast(`${countEnabledPreparedItems(groups)} document(s) ready to review`, 'success');
      }
      if (errors.length > 0) {
        const firstError = String(errors[0]?.error || 'Unknown preparation error');
        showToast(`${errors.length} source(s) could not be prepared (${firstError})`, 'error');
      }
    },
    onError: (error: any) => {
      const message = error?.response?.data?.detail || error?.message || 'Failed to prepare uploaded files';
      showToast(message, 'error');
    },
  });

  const processUploadMutation = useMutation({
    mutationFn: ({
      groups,
      metadataUploadId,
      replaceFileIds,
    }: {
      groups: UploadPreparationGroup[];
      metadataUploadId?: string | null;
      replaceFileIds?: number[];
    }) => ragApi.processPreparedDocuments(groups, metadataUploadId, replaceFileIds),
    onSuccess: (response, variables) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.rag.documents(sessionScope) });
      setIsDragging(false);
      const queuedFiles = Number(
        response?.data?.queued_files || countEnabledPreparedItems(variables.groups)
      );
      if (queuedFiles > 0) {
        showToast(`${queuedFiles} document(s) queued for processing`, 'success');
      }
      const jobId = String(response?.data?.job?.job_id || '');
      if (jobId) {
        watchIngestJob(jobId, queuedFiles === 1 ? 'Document' : `${queuedFiles} documents`);
      }
      closeUploadModal();
      setReplaceConfirm(null);
    },
    onError: (error: any) => {
      const message = error?.response?.data?.detail || error?.message || 'Failed to queue documents';
      showToast(message, 'error');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => ragApi.deleteDocument(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.rag.documents(sessionScope) });
      showToast('Document deleted successfully', 'success');
    },
    onError: () => showToast('Failed to delete document', 'error'),
  });

  const bulkDeleteMutation = useMutation({
    mutationFn: (fileIds: number[]) => ragApi.bulkDeleteDocuments(fileIds),
    onSuccess: (_, fileIds) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.rag.documents(sessionScope) });
      setSelectedDocumentIds((previousIds) =>
        previousIds.filter((fileId) => !fileIds.includes(fileId))
      );
      showToast(`${fileIds.length} document(s) deleted successfully`, 'success');
    },
    onError: () => showToast('Failed to delete selected documents', 'error'),
  });

  const retryMutation = useMutation({
    mutationFn: (doc: any) => ragApi.retryDocument(String(doc?.id || '')),
    onSuccess: (response, doc) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.rag.documents(sessionScope) });
      const jobId = String(response?.data?.job_id || '');
      const label = getDocumentDisplayName(doc);
      if (jobId) {
        watchIngestJob(jobId, label);
      }
      showToast('Document re-queued for processing', 'success');
    },
    onError: (error: any) =>
      showToast(error?.response?.data?.detail || error?.message || 'Failed to retry document', 'error'),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) => ragApi.updateDocument(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.rag.documents(sessionScope) });
      showToast('Document updated successfully', 'success');
      setEditingDocs(null);
    },
    onError: () => showToast('Failed to update document', 'error'),
  });

  const bulkUpdateMutation = useMutation({
    mutationFn: ({ fileIds, data }: { fileIds: number[]; data: any }) =>
      ragApi.bulkUpdateDocuments(fileIds, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.rag.documents(sessionScope) });
      showToast(`${variables.fileIds.length} document(s) updated successfully`, 'success');
      setEditingDocs(null);
    },
    onError: () => showToast('Failed to update selected documents', 'error'),
  });

  const watchIngestJob = useCallback(
    (jobId: string, filename: string, attempt = 0) => {
      if (!jobId) return;
      const maxAttempts = 180;
      const intervalMs = 2000;
      window.setTimeout(async () => {
        try {
          const response = await ragApi.getIngestJob(jobId);
          const status = String(response?.data?.job?.status || '').toLowerCase();
          if (status === 'completed') {
            queryClient.invalidateQueries({ queryKey: queryKeys.rag.documents(sessionScope) });
            return;
          }
          if (status === 'failed') {
            const backendError = String(response?.data?.job?.error || 'Unknown processing error');
            showToast(`${filename}: ${backendError}`, 'error');
            queryClient.invalidateQueries({ queryKey: queryKeys.rag.documents(sessionScope) });
            return;
          }
        } catch (err: unknown) {
          const status = (err as { response?: { status?: number } })?.response?.status;
          // Ingest jobs live in memory on the backend: restart or hot reload can yield a 404.
          if (status === 404) {
            queryClient.invalidateQueries({ queryKey: queryKeys.rag.documents(sessionScope) });
            return;
          }
          // Retry transient failures such as network issues or 5xx responses.
        }
        if (attempt < maxAttempts) {
          watchIngestJob(jobId, filename, attempt + 1);
        }
      }, intervalMs);
    },
    [queryClient, sessionScope, showToast]
  );

  const isAcceptedUploadFile = useCallback((file: File) => {
    const fileName = (file.name || '').toLowerCase();
    const mimeType = (file.type || '').toLowerCase();
    return (
      fileName.endsWith('.pdf') ||
      fileName.endsWith('.zip') ||
      mimeType === 'application/pdf' ||
      mimeType === 'application/zip' ||
      mimeType === 'application/x-zip-compressed' ||
      mimeType === 'multipart/x-zip'
    );
  }, []);

  const prepareUploadDraftFiles = useCallback(
    (incomingFiles: File[]) => {
      const uniqueFiles = Array.from(
        new Map(
          incomingFiles.map((file) => [`${file.name}-${file.size}-${file.lastModified}`, file] as const)
        ).values()
      );
      if (uniqueFiles.length === 0) {
        showToast('Only PDF and ZIP files are allowed', 'error');
        return;
      }
      prepareUploadMutation.mutate(uniqueFiles);
    },
    [prepareUploadMutation, showToast]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const files = Array.from(e.dataTransfer.files).filter((f) => isAcceptedUploadFile(f));
      if (files.length > 0) {
        prepareUploadDraftFiles(files);
      } else {
        showToast('Only PDF and ZIP files are allowed', 'error');
      }
    },
    [isAcceptedUploadFile, prepareUploadDraftFiles, showToast]
  );

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []).filter((f) => isAcceptedUploadFile(f));
    if (files.length > 0) {
      prepareUploadDraftFiles(files);
    } else {
      showToast('Only PDF and ZIP files are allowed', 'error');
    }
    e.target.value = '';
  };

  const handleDownload = async (doc: any) => {
    try {
      const response = await ragApi.downloadDocument(doc.id);
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.download = doc.original_name || doc.filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch {
      showToast('Failed to download document', 'error');
    }
  };

  const documentsRaw = useMemo(
    () => normalizeDocumentsPayload(documentsData?.data),
    [documentsData?.data]
  );
  const queue = summarizeDocumentsQueue(documentsRaw);
  const filteredDocuments = filterRagDocuments(documentsRaw, statusFilter, searchTerm);
  const selectedDocumentIdSet = new Set(selectedDocumentIds);
  const selectedDocuments = getSelectedRagDocuments(documentsRaw, selectedDocumentIds);
  const totalDocuments = filteredDocuments.length;
  const totalPages = Math.ceil(totalDocuments / ITEMS_PER_PAGE);
  const startIndex = (currentPage - 1) * ITEMS_PER_PAGE;
  const endIndex = startIndex + ITEMS_PER_PAGE;
  const documents = filteredDocuments.slice(startIndex, endIndex);
  const selectableCurrentPageDocumentIds = getSelectableDocumentIds(documents);
  const allCurrentPageDocumentsSelected =
    selectableCurrentPageDocumentIds.length > 0 &&
    selectableCurrentPageDocumentIds.every((docId) => selectedDocumentIdSet.has(docId));
  const someCurrentPageDocumentsSelected =
    !allCurrentPageDocumentsSelected &&
    selectableCurrentPageDocumentIds.some((docId) => selectedDocumentIdSet.has(docId));
  const enabledPreparedItems = countEnabledPreparedItems(uploadDraftGroups);
  const totalPreparedItems = countPreparedItems(uploadDraftGroups);
  const hasPreparedUploads = uploadDraftGroups.length > 0;
  const normalizedUploadDraftFilter = uploadDraftFilter.trim().toLowerCase();
  const hasUploadDraftFilter = normalizedUploadDraftFilter.length > 0;
  const hasMetadataSelection = Boolean(selectedMetadataUploadId);
  const selectedMetadataLabel = selectedMetadataUpload
    ? selectedMetadataUpload.display_name || selectedMetadataUpload.source_file_name
    : '';
  const metadataPreviewFileKeySet = new Set(metadataPreviewFileKeys);
  const getUploadDraftMetadataMatchState = (archiveSlug: string): UploadDraftMetadataMatchState => {
    if (!hasMetadataSelection) {
      return 'none';
    }
    if (selectedMetadataUploadId && selectedMetadataDetailQuery.isFetching && metadataPreviewFileKeys.length === 0) {
      return 'loading';
    }
    return metadataPreviewFileKeySet.has(normalizeMetadataFileKey(archiveSlug))
      ? 'matched'
      : 'unmatched';
  };
  const metadataMatchedPreparedItems = countMetadataMatchedPreparedItems(
    uploadDraftGroups,
    metadataPreviewFileKeySet,
    hasMetadataSelection
  );
  const preparedUploadsSummary = buildPreparedUploadsSummary({
    isPreparing: prepareUploadMutation.isPending,
    hasPreparedUploads,
    totalPreparedItems,
    enabledPreparedItems,
    hasMetadataSelection,
    selectedMetadataLabel,
    metadataMatchedPreparedItems,
  });
  const canProcessUploadDraft =
    enabledPreparedItems > 0 &&
    !prepareUploadMutation.isPending &&
    !processUploadMutation.isPending;

  const availableDocumentIdsSignature = useMemo(
    () => getAvailableDocumentIdsSignature(documentsRaw),
    [documentsRaw]
  );

  useEffect(() => {
    const availableDocumentIds = new Set(
      availableDocumentIdsSignature
        ? availableDocumentIdsSignature.split(',').map((value) => Number(value))
        : []
    );
    setSelectedDocumentIds((previousIds) =>
      pruneSelectedDocumentIds(previousIds, availableDocumentIds)
    );
  }, [availableDocumentIdsSignature]);

  useEffect(() => {
    if (!selectAllDocumentsRef.current) {
      return;
    }
    selectAllDocumentsRef.current.indeterminate = someCurrentPageDocumentsSelected;
  }, [someCurrentPageDocumentsSelected]);

  useEffect(() => {
    if (!selectedMetadataUploadId) {
      setMetadataPreviewFileKeys([]);
      return;
    }
    const rowKeys = (selectedMetadataDetailQuery.data?.rows || [])
      .map((row) => normalizeMetadataFileKey(row.file))
      .filter(Boolean);
    setMetadataPreviewFileKeys(Array.from(new Set(rowKeys)));
  }, [selectedMetadataDetailQuery.data?.rows, selectedMetadataUploadId]);

  const filteredUploadDraftGroups = filterUploadDraftGroups(
    uploadDraftGroups,
    uploadDraftFilter
  );

  const clearMetadataSelection = () => {
    setSelectedMetadataUploadId('');
    setMetadataPreviewFileKeys([]);
  };

  const handleExistingMetadataSelect = (metadataUploadId: string) => {
    setSelectedMetadataUploadId(metadataUploadId);
    setMetadataPreviewFileKeys([]);
  };

  const closeUploadModal = () => {
    setShowUploadModal(false);
    setUploadDraftGroups([]);
    clearMetadataSelection();
    setCollapsedUploadGroups({});
    setUploadDraftFilter('');
    setIsDragging(false);
    setReplaceConfirm(null);
    prepareUploadMutation.reset();
    processUploadMutation.reset();
  };

  const removeUploadDraftGroup = (groupSourcePath: string) => {
    setUploadDraftGroups((previousGroups) =>
      removeUploadDraftGroupBySource(previousGroups, groupSourcePath)
    );
    setCollapsedUploadGroups((previousGroups) => {
      if (!(groupSourcePath in previousGroups)) {
        return previousGroups;
      }
      const nextGroups = { ...previousGroups };
      delete nextGroups[groupSourcePath];
      return nextGroups;
    });
  };

  const toggleUploadDraftGroup = (groupSourcePath: string) => {
    setCollapsedUploadGroups((previousGroups) => ({
      ...previousGroups,
      [groupSourcePath]: !previousGroups[groupSourcePath],
    }));
  };

  const updateUploadDraftGroupEnabled = (groupSourcePath: string, enabled: boolean) => {
    setUploadDraftGroups((previousGroups) =>
      setUploadDraftGroupEnabled(previousGroups, groupSourcePath, enabled)
    );
  };

  const updateUploadDraftItem = (
    groupSourcePath: string,
    sourcePath: string,
    patch: Partial<UploadPreparationItem>
  ) => {
    setUploadDraftGroups((previousGroups) =>
      patchUploadDraftItem(previousGroups, groupSourcePath, sourcePath, patch)
    );
  };

  const queueUploadDraft = useCallback(
    (groups: UploadPreparationGroup[], replaceFileIds: number[] = []) => {
      const metadataUploadId = selectedMetadataUploadId || null;
      processUploadMutation.mutate({ groups, metadataUploadId, replaceFileIds });
    },
    [processUploadMutation, selectedMetadataUploadId]
  );

  const submitUploadDraft = () => {
    const enabledItems = uploadDraftGroups.flatMap((group) => group.items).filter((item) => item.enabled);
    if (enabledItems.length === 0) {
      showToast('Select at least one document to process', 'error');
      return;
    }

    const duplicateDocs = findDuplicatePreparedDocuments(documentsRaw, enabledItems);

    if (duplicateDocs.length > 0) {
      setReplaceConfirm({
        duplicateDocs,
        groups: cloneUploadDraftGroups(uploadDraftGroups),
      });
      return;
    }

    void queueUploadDraft(uploadDraftGroups);
  };

  const handleSearchChange = (value: string) => {
    setSearchTerm(value);
    setCurrentPage(1);
  };

  const toggleDocumentSelection = (documentId: number, selected: boolean) => {
    if (!Number.isFinite(documentId) || documentId <= 0) {
      return;
    }
    setSelectedDocumentIds((previousIds) =>
      toggleSelectedDocumentId(previousIds, documentId, selected)
    );
  };

  const toggleAllVisibleDocuments = (selected: boolean) => {
    setSelectedDocumentIds((previousIds) =>
      toggleVisibleDocumentIds(previousIds, selectableCurrentPageDocumentIds, selected)
    );
  };

  const openSingleDocumentEditor = (doc: any) => {
    setEditingDocs([doc]);
  };

  const openBulkDocumentEditor = () => {
    if (selectedDocuments.length === 0) {
      return;
    }
    setEditingDocs(selectedDocuments);
  };

  const openSingleDocumentDeleteConfirm = (doc: any) => {
    setDeletingDocs([doc]);
  };

  const openBulkDocumentDeleteConfirm = () => {
    if (selectedDocuments.length === 0) {
      return;
    }
    setDeletingDocs(selectedDocuments);
  };

  return (
    <Layout>
      <div className="space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 mb-2">Retrieval-Augmented Generation (RAG)</h1>
          </div>
          <button
            type="button"
              onClick={() => {
                setShowUploadModal(true);
                setUploadDraftGroups([]);
                clearMetadataSelection();
                setIsDragging(false);
                setReplaceConfirm(null);
              }}
            className="flex-shrink-0 inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white bg-oracle-red hover:bg-oracle-red/90 border border-transparent transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            File
          </button>
        </div>

        <div className="app-light-surface rag-light-surface bg-white rounded-lg shadow p-8 space-y-6">
          <RAGQueueSummary queue={queue} />

          <RAGToolbar
            searchTerm={searchTerm}
            statusFilter={statusFilter}
            isAdmin={isAdmin}
            isLoading={isLoading}
            selectedCount={selectedDocuments.length}
            editPending={bulkUpdateMutation.isPending || updateMutation.isPending}
            deletePending={bulkDeleteMutation.isPending || deleteMutation.isPending}
            onSearchChange={handleSearchChange}
            onStatusChange={(value) => {
              setStatusFilter(value);
              setCurrentPage(1);
            }}
            onRefresh={() => {
              queryClient.refetchQueries({ queryKey: queryKeys.rag.documents(sessionScope) });
            }}
            onBulkEdit={openBulkDocumentEditor}
            onBulkDelete={openBulkDocumentDeleteConfirm}
          />

          <RAGDocumentTable
            documents={documents}
            isLoading={isLoading}
            searchTerm={searchTerm}
            isAdmin={isAdmin}
            selectedDocumentIdSet={selectedDocumentIdSet}
            allCurrentPageDocumentsSelected={allCurrentPageDocumentsSelected}
            selectAllDocumentsRef={selectAllDocumentsRef}
            deletePending={deleteMutation.isPending}
            retryPending={retryMutation.isPending}
            totalDocuments={totalDocuments}
            startIndex={startIndex}
            endIndex={endIndex}
            currentPage={currentPage}
            totalPages={totalPages}
            onToggleDocumentSelection={toggleDocumentSelection}
            onToggleAllVisibleDocuments={toggleAllVisibleDocuments}
            onViewDocument={setViewingDoc}
            onDownloadDocument={handleDownload}
            onEditDocument={openSingleDocumentEditor}
            onRetryDocument={(document) => retryMutation.mutate(document)}
            onDeleteDocument={openSingleDocumentDeleteConfirm}
            onPreviousPage={() => setCurrentPage((page) => Math.max(1, page - 1))}
            onNextPage={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
          />
        </div>

        {showUploadModal && (
          <RAGUploadModal
            preparedUploadsSummary={preparedUploadsSummary}
            selectedMetadataUploadId={selectedMetadataUploadId}
            selectedMetadataUpload={selectedMetadataUpload}
            selectedMetadataLabel={selectedMetadataLabel}
            metadataUploads={metadataUploadsQuery.data || []}
            metadataUploadsLoading={metadataUploadsQuery.isLoading}
            hasPreparedUploads={hasPreparedUploads}
            preparePending={prepareUploadMutation.isPending}
            processPending={processUploadMutation.isPending}
            uploadDraftFilter={uploadDraftFilter}
            isDragging={isDragging}
            totalPreparedItems={totalPreparedItems}
            metadataMatchedPreparedItems={metadataMatchedPreparedItems}
            hasMetadataSelection={hasMetadataSelection}
            canProcessUploadDraft={canProcessUploadDraft}
            onClose={closeUploadModal}
            onFileSelect={handleFileSelect}
            onMetadataSelect={handleExistingMetadataSelect}
            onUploadDraftFilterChange={setUploadDraftFilter}
            onClearUploadDraftFilter={() => setUploadDraftFilter('')}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onSubmit={submitUploadDraft}
          >
            <RAGUploadDraftList
              filteredUploadDraftGroups={filteredUploadDraftGroups}
              uploadDraftFilter={uploadDraftFilter}
              hasUploadDraftFilter={hasUploadDraftFilter}
              collapsedUploadGroups={collapsedUploadGroups}
              onToggleGroup={toggleUploadDraftGroup}
              onRemoveGroup={removeUploadDraftGroup}
              onSetGroupEnabled={updateUploadDraftGroupEnabled}
              onUpdateItem={updateUploadDraftItem}
              getMetadataMatchState={getUploadDraftMetadataMatchState}
            />
          </RAGUploadModal>
        )}

        {replaceConfirm && (
          <RAGReplaceConfirmModal
            duplicateDocs={replaceConfirm.duplicateDocs}
            processPending={processUploadMutation.isPending}
            onCancel={() => setReplaceConfirm(null)}
            onConfirm={() => {
              const { duplicateDocs, groups } = replaceConfirm;
              const replaceFileIds = duplicateDocs
                .map((doc: any) => Number(doc.id))
                .filter((value) => Number.isFinite(value) && value > 0);
              void queueUploadDraft(groups, replaceFileIds);
            }}
          />
        )}

        {editingDocs && editingDocs.length > 0 && (
          <EditDocumentModal
            docs={editingDocs}
            onClose={() => setEditingDocs(null)}
            onSave={(data) => {
              const fileIds = editingDocs
                .map((doc) => Number(doc.id))
                .filter((fileId) => Number.isFinite(fileId) && fileId > 0);
              if (fileIds.length <= 1) {
                const singleFileId = String(fileIds[0] || '');
                updateMutation.mutate({ id: singleFileId, data });
                return;
              }
              bulkUpdateMutation.mutate({ fileIds, data });
            }}
            isSaving={updateMutation.isPending || bulkUpdateMutation.isPending}
          />
        )}

        {viewingDoc && (
          <DocumentViewerModal
            doc={viewingDoc}
            onClose={() => setViewingDoc(null)}
          />
        )}

        {deletingDocs && deletingDocs.length > 0 && (
          <ConfirmDeleteModal
            title={deletingDocs.length > 1 ? 'Delete documents' : 'Delete document'}
            message={
              <DeleteDocumentConfirmMessage
                docNames={deletingDocs.map((doc) =>
                  String(doc.original_name || doc.filename || '')
                )}
              />
            }
            detail={deletingDocs.length > 1 ? 'All selected documents will be removed.' : 'This action cannot be undone.'}
            loading={deleteMutation.isPending || bulkDeleteMutation.isPending}
            onConfirm={() => {
              const fileIds = deletingDocs
                .map((doc) => Number(doc.id))
                .filter((fileId) => Number.isFinite(fileId) && fileId > 0);
              if (fileIds.length <= 1) {
                deleteMutation.mutate(String(fileIds[0] || ''), {
                  onSuccess: () => setDeletingDocs(null),
                  onError: () => setDeletingDocs(null),
                });
                return;
              }
              bulkDeleteMutation.mutate(fileIds, {
                onSuccess: () => setDeletingDocs(null),
                onError: () => setDeletingDocs(null),
              });
            }}
            onCancel={() => setDeletingDocs(null)}
          />
        )}
      </div>
    </Layout>
  );
}
