import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Layout } from '../common/Layout';
import { ConfirmDeleteModal } from '../common/ConfirmDeleteModal';
import { LoadingState } from '../common/LoadingState';
import { ModalPortal } from '../common/ModalPortal';
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
  ACCESS_OPTIONS,
  compactUploadDraftFieldLabelClassName,
  compactUploadDraftSelectClassName,
  countEnabledPreparedItems,
  DEFAULT_UPLOAD_ACCESS,
  DEFAULT_UPLOAD_LANGUAGE,
  DeleteDocumentConfirmMessage,
  documentToolbarButtonClassName,
  formatCountLabel,
  formatUploadGroupKind,
  getDocumentDisplayName,
  getPreparedItemKey,
  getUploadDraftMetadataMatchPresentation,
  hasDocumentsInFlight,
  ITEMS_PER_PAGE,
  LANGUAGE_OPTIONS,
  mergePreparedGroups,
  normalizeDocumentsPayload,
  normalizeMetadataFileKey,
  summarizeDocumentsQueue,
  uploadDraftActionButtonClassName,
  uploadDraftControlGridClassName,
  uploadDraftMetadataSelectClassName,
  uploadDraftRowGridClassName,
} from './RAG.model';
import type {
  UploadDraftMetadataMatchState,
} from './RAG.model';
import { DocumentViewerModal } from './RAGDocumentViewerModal';
import { RAGDocumentTable } from './RAGDocumentTable';
import { EditDocumentModal } from './RAGEditDocumentModal';

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
  const filteredDocuments = documentsRaw.filter((doc: any) => {
    if (statusFilter && String(doc?.status || '') !== statusFilter) {
      return false;
    }
    if (!searchTerm) return true;
    const search = searchTerm.toLowerCase();
    return doc.filename?.toLowerCase().includes(search) ||
           doc.original_name?.toLowerCase().includes(search) ||
           getDocumentDisplayName(doc).toLowerCase().includes(search);
  });
  const selectedDocumentIdSet = new Set(selectedDocumentIds);
  const selectedDocuments = documentsRaw.filter((doc: any) =>
    selectedDocumentIdSet.has(Number(doc.id))
  );
  const totalDocuments = filteredDocuments.length;
  const totalPages = Math.ceil(totalDocuments / ITEMS_PER_PAGE);
  const startIndex = (currentPage - 1) * ITEMS_PER_PAGE;
  const endIndex = startIndex + ITEMS_PER_PAGE;
  const documents = filteredDocuments.slice(startIndex, endIndex);
  const selectableCurrentPageDocumentIds = documents
    .map((doc: any) => Number(doc.id))
    .filter((docId) => Number.isFinite(docId) && docId > 0);
  const allCurrentPageDocumentsSelected =
    selectableCurrentPageDocumentIds.length > 0 &&
    selectableCurrentPageDocumentIds.every((docId) => selectedDocumentIdSet.has(docId));
  const someCurrentPageDocumentsSelected =
    !allCurrentPageDocumentsSelected &&
    selectableCurrentPageDocumentIds.some((docId) => selectedDocumentIdSet.has(docId));
  const enabledPreparedItems = countEnabledPreparedItems(uploadDraftGroups);
  const totalPreparedItems = uploadDraftGroups.reduce(
    (total, group) => total + group.items.length,
    0
  );
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
  const metadataMatchedPreparedItems = hasMetadataSelection
    ? uploadDraftGroups.reduce(
        (total, group) =>
          total +
          group.items.filter((item) =>
            metadataPreviewFileKeySet.has(normalizeMetadataFileKey(item.archive_slug))
          ).length,
        0
      )
    : 0;
  const preparedUploadsSummary = prepareUploadMutation.isPending
    ? 'Preparing files...'
    : hasPreparedUploads
    ? `${formatCountLabel(totalPreparedItems, 'file')} total \u00B7 ${enabledPreparedItems} selected${
        hasMetadataSelection
          ? ` \u00B7 metadata ${selectedMetadataLabel || 'selected'} (${metadataMatchedPreparedItems} matched)`
          : ''
      }`
    : `Select PDF or ZIP files to prepare the ingestion batch.${
        hasMetadataSelection ? ` Metadata: ${selectedMetadataLabel || 'selected'}` : ''
      }`;
  const canProcessUploadDraft =
    enabledPreparedItems > 0 &&
    !prepareUploadMutation.isPending &&
    !processUploadMutation.isPending;

  const availableDocumentIdsSignature = useMemo(
    () =>
      documentsRaw
        .map((doc: any) => Number(doc.id))
        .filter((docId) => Number.isFinite(docId) && docId > 0)
        .sort((left, right) => left - right)
        .join(','),
    [documentsRaw]
  );

  useEffect(() => {
    const availableDocumentIds = new Set(
      availableDocumentIdsSignature
        ? availableDocumentIdsSignature.split(',').map((value) => Number(value))
        : []
    );
    setSelectedDocumentIds((previousIds) => {
      const nextIds = previousIds.filter((docId) => availableDocumentIds.has(docId));
      if (
        nextIds.length === previousIds.length &&
        nextIds.every((docId, index) => docId === previousIds[index])
      ) {
        return previousIds;
      }
      return nextIds;
    });
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

  const filteredUploadDraftGroups = uploadDraftGroups.reduce<
    Array<{
      group: UploadPreparationGroup;
      items: UploadPreparationItem[];
      groupMatches: boolean;
    }>
  >((accumulator, group) => {
    if (!hasUploadDraftFilter) {
      accumulator.push({
        group,
        items: group.items,
        groupMatches: false,
      });
      return accumulator;
    }

    const groupSearchText = [group.group_name, group.group_kind, group.archive_slug]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();
    const groupMatches = groupSearchText.includes(normalizedUploadDraftFilter);
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
            .includes(normalizedUploadDraftFilter)
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
      previousGroups.filter((group) => group.group_source_path !== groupSourcePath)
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
      previousGroups.map((group) => {
        if (group.group_source_path !== groupSourcePath) {
          return group;
        }
        return {
          ...group,
          items: group.items.map((item) => ({ ...item, enabled })),
        };
      })
    );
  };

  const updateUploadDraftItem = (
    groupSourcePath: string,
    sourcePath: string,
    patch: Partial<UploadPreparationItem>
  ) => {
    setUploadDraftGroups((previousGroups) =>
      previousGroups.map((group) => {
        if (group.group_source_path !== groupSourcePath) {
          return group;
        }
        return {
          ...group,
          items: group.items.map((item) =>
            item.source_path === sourcePath ? { ...item, ...patch } : item
          ),
        };
      })
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

    const duplicateById = new Map<string, any>();
    documentsRaw.forEach((document: any) => {
      const documentName = String(document.original_name || document.filename || '').trim().toLowerCase();
      if (!documentName) {
        return;
      }
      if (enabledItems.some((item) => item.file_name.toLowerCase() === documentName)) {
        duplicateById.set(String(document.id), document);
      }
    });
    const duplicateDocs = Array.from(duplicateById.values());

    if (duplicateDocs.length > 0) {
      setReplaceConfirm({
        duplicateDocs,
        groups: uploadDraftGroups.map((group) => ({
          ...group,
          items: group.items.map((item) => ({ ...item })),
        })),
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
    setSelectedDocumentIds((previousIds) => {
      if (selected) {
        return previousIds.includes(documentId) ? previousIds : [...previousIds, documentId];
      }
      return previousIds.filter((currentId) => currentId !== documentId);
    });
  };

  const toggleAllVisibleDocuments = (selected: boolean) => {
    setSelectedDocumentIds((previousIds) => {
      const previousIdSet = new Set(previousIds);
      if (selected) {
        selectableCurrentPageDocumentIds.forEach((documentId) => previousIdSet.add(documentId));
      } else {
        selectableCurrentPageDocumentIds.forEach((documentId) => previousIdSet.delete(documentId));
      }
      return Array.from(previousIdSet);
    });
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

  const highlightText = (text: string | undefined, search: string) => {
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
          {/* Queue Status */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            <div className="h-10 rounded-xl border border-amber-200 bg-amber-50/60 shadow-sm px-3 flex items-center justify-between">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-900/80 truncate">Pending</p>
              <p className="text-xl font-bold leading-none tabular-nums text-amber-700">{queue.pending || 0}</p>
            </div>
            <div className="h-10 rounded-xl border border-blue-200 bg-blue-50/60 shadow-sm px-3 flex items-center justify-between">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-blue-900/80 truncate">OCR</p>
              <p className="text-xl font-bold leading-none tabular-nums text-blue-700">{queue.processing_ocr || 0}</p>
            </div>
            <div className="h-10 rounded-xl border border-rose-200 bg-rose-50/60 shadow-sm px-3 flex items-center justify-between">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-rose-900/80 truncate">Error</p>
              <p className="text-xl font-bold leading-none tabular-nums text-rose-700">{queue.error || 0}</p>
            </div>
            <div className="h-10 rounded-xl border border-emerald-200 bg-emerald-50/60 shadow-sm px-3 flex items-center justify-between">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-emerald-900/80 truncate">Completed</p>
              <p className="text-xl font-bold leading-none tabular-nums text-emerald-700">{queue.completed || 0}</p>
            </div>
          </div>

          {/* Search and Filter */}
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
            <div className="grid flex-1 grid-cols-1 gap-3 md:grid-cols-[1fr_150px]">
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => handleSearchChange(e.target.value)}
                placeholder="Search by filename..."
                className="input-oracle"
              />
              <select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                  setCurrentPage(1);
                }}
                className="input-oracle"
              >
                <option value="">All statuses</option>
                <option value="completed">Completed</option>
                <option value="pending">Pending</option>
                <option value="processing_ocr">OCR</option>
                <option value="error">Error</option>
              </select>
            </div>

            <div className="flex flex-wrap items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  queryClient.refetchQueries({ queryKey: queryKeys.rag.documents(sessionScope) });
                }}
                disabled={isLoading}
                title="Refresh"
                className={`${documentToolbarButtonClassName} w-10 px-0`}
                aria-label="Refresh"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </button>
              {isAdmin && (
                <>
                  <button
                    type="button"
                    onClick={openBulkDocumentEditor}
                    disabled={selectedDocuments.length === 0 || bulkUpdateMutation.isPending || updateMutation.isPending}
                    className={`${documentToolbarButtonClassName} w-10 px-0`}
                    title="Edit selected documents"
                    aria-label="Edit selected documents"
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    onClick={openBulkDocumentDeleteConfirm}
                    disabled={selectedDocuments.length === 0 || bulkDeleteMutation.isPending || deleteMutation.isPending}
                    className={`${documentToolbarButtonClassName} w-10 px-0`}
                    title="Delete selected documents"
                    aria-label="Delete selected documents"
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </>
              )}
            </div>
          </div>

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
          <ModalPortal zIndex="z-[300]" className="items-start justify-center p-4">
            <div
              className="rounded-2xl shadow-2xl overflow-hidden max-w-6xl w-full border-0 max-h-[min(820px,calc(100vh-2rem))] flex flex-col"
              style={{
                background: 'rgba(255,255,255,0.72)',
                backdropFilter: 'blur(20px) saturate(180%)',
                WebkitBackdropFilter: 'blur(20px) saturate(180%)',
              }}
            >
              <div className="bg-oracle-dark-gray px-5 py-4">
                <div className="flex items-start gap-4">
                  <div className="min-w-0">
                    <h2 className="text-lg font-semibold text-white">Files</h2>
                    <p className="mt-1 text-sm text-gray-200">{preparedUploadsSummary}</p>
                  </div>

                  <div className="ml-auto flex items-center gap-2">
                    <button
                      type="button"
                      onClick={closeUploadModal}
                      className="p-1.5 rounded-lg hover:bg-white/10 transition-colors text-gray-200"
                      aria-label="Close upload modal"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>

              <div className="bg-white px-6 pb-6 pt-4 flex flex-1 min-h-0 flex-col gap-4">
                <input
                  id="upload-rag-files-input"
                  type="file"
                  multiple
                  accept=".pdf,.zip"
                  onChange={handleFileSelect}
                  className="hidden"
                />

                <div className="-mx-6 -mt-4 flex flex-1 min-h-0 flex-col overflow-hidden border-y border-gray-200 bg-white">
                  <div className="border-b border-gray-200 bg-gray-50 px-4 py-3">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                      <div className="flex flex-wrap items-center gap-2">
                        <label
                          htmlFor="upload-rag-files-input"
                          className={uploadDraftActionButtonClassName}
                        >
                          + Add files
                        </label>

                        <select
                          value={selectedMetadataUploadId}
                          onChange={(e) => handleExistingMetadataSelect(e.target.value)}
                          disabled={metadataUploadsQuery.isLoading}
                          className={uploadDraftMetadataSelectClassName}
                          title="Select an existing metadata dataset"
                        >
                          <option value="">
                            {metadataUploadsQuery.isLoading ? 'Loading metadata...' : 'Select metadata...'}
                          </option>
                          {(metadataUploadsQuery.data || []).map((dataset: MetadataUploadSummary) => (
                            <option key={dataset.metadata_upload_id} value={dataset.metadata_upload_id}>
                              {dataset.display_name || dataset.source_file_name} ({dataset.columns.length} cols)
                            </option>
                          ))}
                        </select>
                      </div>

                      {hasPreparedUploads && (
                        <div className="relative flex-1">
                          <input
                            type="text"
                            value={uploadDraftFilter}
                            onChange={(e) => setUploadDraftFilter(e.target.value)}
                            placeholder="Filter by folder or document..."
                            className="input-oracle w-full pr-10"
                          />
                          {uploadDraftFilter && (
                            <button
                              type="button"
                              onClick={() => setUploadDraftFilter('')}
                              className="absolute inset-y-0 right-2 flex items-center rounded-md px-2 text-oracle-light-gray transition-colors hover:text-oracle-dark-gray"
                              aria-label="Clear upload filter"
                            >
                              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                              </svg>
                            </button>
                          )}
                        </div>
                      )}
                    </div>

                    <p className="mt-2 text-xs text-oracle-medium-gray">
                      The first column must be exactly <code>file</code> and match the logical archive name without
                      extension. Upload or update metadata from the Metadata module, then select it here.
                      {selectedMetadataUpload ? (
                        <>
                          {' '}
                          <span className="font-medium text-oracle-dark-gray">
                            Metadata selected: {selectedMetadataLabel}.
                          </span>
                        </>
                      ) : null}
                      {hasMetadataSelection && totalPreparedItems > 0
                        ? ` Current batch: ${metadataMatchedPreparedItems} matched, ${
                            totalPreparedItems - metadataMatchedPreparedItems
                          } without metadata.`
                        : ''}
                    </p>
                  </div>

                  {!hasPreparedUploads ? (
                    prepareUploadMutation.isPending ? (
                      <div className="flex flex-1 min-h-[280px] items-center justify-center px-6 py-12">
                        <LoadingState
                          size="md"
                          label="Preparing files..."
                          textClassName="text-oracle-medium-gray"
                        />
                      </div>
                    ) : (
                      <div className="flex flex-1 items-center p-6">
                        <div
                          className={`w-full border-2 border-dashed rounded-lg px-6 py-6 text-center transition-all cursor-pointer ${
                            isDragging
                              ? 'border-oracle-red bg-red-50'
                              : 'border-gray-300 bg-gray-50 hover:bg-gray-100'
                          }`}
                          onDragEnter={handleDragOver}
                          onDragLeave={handleDragLeave}
                          onDragOver={handleDragOver}
                          onDrop={handleDrop}
                        >
                          <div className="text-gray-600 mb-1">
                            <strong>Drag and Drop</strong>
                          </div>
                          <div className="text-sm text-gray-500 mb-1">
                            Select one or more PDF or ZIP files, or drop them here
                          </div>
                          <div className="text-xs text-gray-500 mb-2">
                            ZIP uploads are expanded first so you can review metadata coverage, language, and access.
                          </div>
                          <label
                            htmlFor="upload-rag-files-input"
                            className="text-oracle-blue-link hover:underline text-sm cursor-pointer"
                          >
                            Select file(s)
                          </label>
                        </div>
                      </div>
                    )
                  ) : (
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
                            onClick={() => toggleUploadDraftGroup(group.group_source_path)}
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
                            onChange={(e) =>
                              updateUploadDraftGroupEnabled(group.group_source_path, e.target.checked)
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
                            onClick={() => toggleUploadDraftGroup(group.group_source_path)}
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
                            onClick={() => removeUploadDraftGroup(group.group_source_path)}
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
                                item.enabled
                                  ? 'border-gray-100 bg-white'
                                  : 'border-gray-100 bg-gray-50/70'
                              }`}
                            >
                              <div className="px-4 py-1 pl-16">
                                <div className={uploadDraftRowGridClassName}>
                                  <div className="flex min-w-0 items-start gap-3 xl:items-center">
                                    <input
                                      type="checkbox"
                                      checked={item.enabled}
                                      onChange={(e) =>
                                        updateUploadDraftItem(group.group_source_path, item.source_path, {
                                          enabled: e.target.checked,
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
                                      {(() => {
                                        const metadataMatchState = getUploadDraftMetadataMatchState(
                                          item.archive_slug
                                        );
                                        const metadataMatchPresentation =
                                          getUploadDraftMetadataMatchPresentation(metadataMatchState);
                                        const metadataMatchTitle =
                                          metadataMatchState === 'matched'
                                            ? `Matched metadata row for ${item.archive_slug}`
                                            : metadataMatchState === 'unmatched'
                                            ? `No metadata row matched ${item.archive_slug}`
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
                                      })()}
                                    </div>
                                    <label className={compactUploadDraftFieldLabelClassName}>
                                      <span className="text-[11px] font-semibold uppercase tracking-wide text-oracle-medium-gray xl:hidden">
                                        Language
                                      </span>
                                      <select
                                        value={item.document_language || DEFAULT_UPLOAD_LANGUAGE}
                                        onChange={(e) =>
                                          updateUploadDraftItem(group.group_source_path, item.source_path, {
                                            document_language: e.target.value,
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
                                        onChange={(e) =>
                                          updateUploadDraftItem(group.group_source_path, item.source_path, {
                                            access: e.target.value,
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
                  )}
                </div>

                <div className="flex shrink-0 gap-3 justify-end pt-2">
                  <button type="button" onClick={closeUploadModal} className="btn-secondary">
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={submitUploadDraft}
                    disabled={!canProcessUploadDraft}
                    className="btn-primary"
                  >
                    {processUploadMutation.isPending
                      ? 'Processing...'
                      : prepareUploadMutation.isPending
                      ? 'Preparing...'
                      : 'Process files'}
                  </button>
                </div>
              </div>
            </div>
          </ModalPortal>
        )}

        {replaceConfirm && (
          <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50">
            <div className="bg-white rounded-lg w-full max-w-md max-h-[min(80vh,720px)] overflow-hidden">
              <div className="p-6 flex min-h-0 flex-1 flex-col">
                <h2 className="text-lg font-bold text-oracle-dark-gray mb-2">Document already exists</h2>
                <p className="text-sm text-oracle-medium-gray mb-4">
                  A document with this name already exists ({replaceConfirm.duplicateDocs.length}):
                </p>
                <ul className="list-disc list-inside text-sm text-oracle-dark-gray mb-4 max-h-72 overflow-y-auto pr-2">
                  {replaceConfirm.duplicateDocs.map((d: any) => (
                    <li key={d.id}>{d.original_name || d.filename}</li>
                  ))}
                </ul>
                <p className="text-sm text-oracle-medium-gray">
                  Do you want to reprocess it? The existing document will be deleted and processed again.
                </p>
                <div className="mt-4 flex gap-2 justify-end border-t border-gray-100 pt-4">
                  <button
                    type="button"
                    onClick={() => setReplaceConfirm(null)}
                    className="btn-secondary"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const { duplicateDocs, groups } = replaceConfirm;
                      const replaceFileIds = duplicateDocs
                        .map((doc: any) => Number(doc.id))
                        .filter((value) => Number.isFinite(value) && value > 0);
                      void queueUploadDraft(groups, replaceFileIds);
                    }}
                    disabled={processUploadMutation.isPending}
                    className="btn-primary"
                  >
                    {processUploadMutation.isPending
                      ? 'Processing...'
                      : 'Yes, reprocess'}
                  </button>
                </div>
              </div>
            </div>
          </div>
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
