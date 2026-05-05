import axios from 'axios';

const baseURL = '/api';

const api = axios.create({
  baseURL,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  if (config.data instanceof FormData) {
    delete config.headers['Content-Type'];
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      const requestUrl = error?.config?.url ?? '';
      if (!requestUrl.includes('/auth/login')) {
        localStorage.removeItem('token');
        sessionStorage.removeItem('builder-last-flow-id');
        sessionStorage.removeItem('flow-builder-state');
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export { baseURL };

export type ChatConversationSummary = {
  conversation_id: number;
  title: string;
  turns: number;
  last_message_preview: string;
  created_at: string;
  updated_at: string;
};

export type ReasoningStage = {
  key: string;
  label: string;
  starts_at_seconds: number;
};

export type ReasoningResult = {
  strategy: string;
  answer_mode: string;
  visual_confirmation_used: boolean;
  analyzed_pages: number[];
  confidence_notes: string[];
};

export type ChatSource = {
  doc_id: string;
  name: string;
  source_number?: number;
  file_id?: number;
  page_number?: number;
  object_name_page?: string;
  snippet?: string;
};

export type GraphNodeDefinition = {
  key: string;
  label: string;
  kind: string;
};

export type GraphEdgeDefinition = {
  source: string;
  target: string;
  condition?: string;
};

export type GraphDefinition = {
  nodes: GraphNodeDefinition[];
  edges: GraphEdgeDefinition[];
  start_node: string;
  end_node: string;
};

export type RAGScopeOptions = {
  files: string[];
  metadata_fields: string[];
  has_metadata: boolean;
};

export type GraphRuntimeEvent = {
  event_type: string;
  thread_id?: string;
  timestamp?: string;
  langgraph_type?: string;
  node_key?: string;
  status?: string;
  payload?: any;
  state_patch?: Record<string, any>;
  execution?: Record<string, any>;
  final_response?: Record<string, any>;
  error?: string;
  duration_ms?: number;
};

export type SummaryMode = 'default' | 'per_document';

export type ChatRequestOptions = {
  allow_inferred_scope?: boolean;
  top_k?: number;
  candidate_k?: number;
  min_pages_per_selected_doc?: number;
  summary_mode?: SummaryMode;
  metadata_mode?: 'auto' | 'metadata_first';
  archive_slugs?: string[];
  metadata_fields?: string[];
};

export type UploadPreparationItem = {
  source_path: string;
  source_zip_path?: string | null;
  group_source_path: string;
  group_name: string;
  group_kind: string;
  archive_slug: string;
  file_name: string;
  display_name: string;
  document_code?: string | null;
  document_code_source: string;
  document_language: string;
  access: string;
  order: number;
  enabled: boolean;
};

export type UploadPreparationGroup = {
  group_source_path: string;
  group_name: string;
  group_kind: string;
  archive_slug: string;
  item_count: number;
  items: UploadPreparationItem[];
};

export type UploadPreparationError = {
  source_path: string;
  source_name: string;
  error: string;
};

export type UploadPreparationResponse = {
  groups: UploadPreparationGroup[];
  errors: UploadPreparationError[];
};

export type MetadataUploadMatchSummary = {
  matched_files: string[];
  unmatched_files: string[];
  duplicate_files: string[];
};

export type MetadataUploadResponse = {
  metadata_upload_id: string;
  source_file_name: string;
  display_name: string;
  description: string;
  access_scope: 'private' | 'all';
  metadata_status: string;
  created_at: string;
  columns: string[];
  total_rows: number;
  match_summary: MetadataUploadMatchSummary;
};

export type MetadataUploadSummary = {
  metadata_upload_id: string;
  owner_user_id: number;
  source_file_name: string;
  display_name: string;
  description: string;
  access_scope: 'private' | 'all';
  metadata_status: string;
  columns: string[];
  total_rows: number;
  row_count: number;
  matched_files_count: number;
  unmatched_files_count: number;
  linked_documents_count: number;
  created_at: string;
  updated_at: string;
};

export type MetadataUploadRowPreview = {
  file: string;
  fields: Record<string, unknown>;
};

export type MetadataUploadListResponse = {
  items: MetadataUploadSummary[];
};

export type MetadataUploadDetailResponse = MetadataUploadSummary & {
  rows: MetadataUploadRowPreview[];
};

export type MetadataUploadUpdateRequest = {
  display_name?: string | null;
  description?: string | null;
  metadata_status?: 'active' | 'archived';
  access_scope?: 'private' | 'all';
};

function normalizeSourceItems(sourceItems: any[], evidenceBySource: Map<number, any>): ChatSource[] {
  return sourceItems.map((item: any, index: number) => {
    const sourceNumber = Number(item?.source_number ?? item?.doc_id ?? 0);
    const matchedEvidence = evidenceBySource.get(sourceNumber);
    const fileName = String(item?.file_name || '').trim();
    const pageNumber = Number(item?.page_number ?? matchedEvidence?.page_number ?? 0);
    const fallbackName = String(item?.name || '').trim();
    const snippet = String(item?.snippet ?? matchedEvidence?.summary_text ?? '').trim();
    return {
      doc_id: String(item?.doc_id || item?.source_number || index + 1),
      name: fallbackName || `${fileName || 'document'} - page ${pageNumber || '?'}`,
      source_number: sourceNumber || undefined,
      file_id: Number(item?.file_id ?? matchedEvidence?.file_id ?? 0) || undefined,
      page_number: pageNumber || undefined,
      object_name_page: String(item?.object_name_page ?? matchedEvidence?.object_name_page ?? ''),
      snippet: snippet || undefined,
    };
  });
}

function normalizeAskResponsePayload(data: any) {
  const evidenceBySource = new Map<number, any>();
  if (Array.isArray(data?.evidence)) {
    for (const item of data.evidence) {
      const key = Number(item?.source_number ?? 0);
      if (!Number.isNaN(key) && key > 0) {
        evidenceBySource.set(key, item);
      }
    }
  }
  const sourceItems = Array.isArray(data?.sources)
    ? data.sources
    : Array.isArray(data?.citations)
    ? data.citations
    : [];
  const sources: ChatSource[] = normalizeSourceItems(sourceItems, evidenceBySource);
  const citedSources: ChatSource[] = Array.isArray(data?.cited_sources)
    ? normalizeSourceItems(data.cited_sources, evidenceBySource)
    : [];
  const retrievedSources: ChatSource[] = Array.isArray(data?.retrieved_sources)
    ? normalizeSourceItems(data.retrieved_sources, evidenceBySource)
    : [];
  return {
    success: true,
    reply: data?.answer || data?.answer_text || '',
    sources,
    citedSources,
    retrievedSources,
    model_used: data?.model_used || '',
    thread_id: String(data?.thread_id || ''),
    reasoning: {
      strategy: String(data?.strategy || ''),
      answer_mode: String(data?.answer_mode || ''),
      visual_confirmation_used: Boolean(data?.visual_confirmation_used),
      analyzed_pages: Array.isArray(data?.analyzed_pages)
        ? data.analyzed_pages
            .map((value: unknown) => Number(value))
            .filter((value: number) => !Number.isNaN(value))
        : [],
      confidence_notes: Array.isArray(data?.confidence_notes)
        ? data.confidence_notes
            .map((value: unknown) => String(value || '').trim())
            .filter((value: string) => Boolean(value))
        : [],
    } as ReasoningResult,
    telemetry: typeof data?.telemetry === 'object' && data?.telemetry !== null ? data.telemetry : {},
  };
}

export const ragApi = {
  listDocuments: (status?: string) =>
    api.get('/files', {
      params: status ? { status } : undefined,
      timeout: 15000,
    }),
  prepareUploadPlan: async (
    files: File[],
    defaultAccess: string = 'private',
    defaultDocumentLanguage: string = 'es'
  ) => {
    const formData = new FormData();
    for (const file of files) {
      formData.append('files', file);
    }
    const uploadResp = await api.post('/files/upload', formData);
    const savedFiles = Array.isArray(uploadResp?.data?.saved_files) ? uploadResp.data.saved_files : [];
    if (savedFiles.length !== files.length) {
      throw new Error('The backend did not return a saved path for every uploaded file.');
    }
    return api.post<UploadPreparationResponse>('/files/prepare', {
      saved_files: savedFiles,
      default_document_language: defaultDocumentLanguage,
      default_access: defaultAccess,
    });
  },
  uploadMetadataCsv: (file: File, accessScope: 'private' | 'all' = 'private') => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('access_scope', accessScope);
    return api.post<MetadataUploadResponse>('/metadata/upload', formData);
  },
  processPreparedDocuments: (
    groups: UploadPreparationGroup[],
    metadataUploadId?: string | null,
    replaceFileIds?: number[]
  ) => {
    const items = groups
      .flatMap((group) => group.items)
      .filter((item) => item.enabled)
      .map((item) => ({
        source_path: item.source_path,
        source_zip_path: item.source_zip_path || null,
        archive_slug: item.archive_slug,
        file_name: item.file_name,
        group_name: item.group_name,
        display_name: item.display_name,
        document_language: item.document_language,
        access: item.access,
        document_code: item.document_code ?? null,
        document_code_source: item.document_code_source,
        enabled: item.enabled,
      }));
    return api.post('/files/process-batch', {
      metadata_upload_id: metadataUploadId ?? null,
      replace_file_ids: Array.isArray(replaceFileIds) ? replaceFileIds : [],
      items,
    });
  },
  updateDocument: (id: string, data: any) => api.put(`/files/${id}`, data),
  bulkUpdateDocuments: (fileIds: number[], data: any) =>
    api.put('/files/bulk/access', {
      file_ids: fileIds,
      ...data,
    }),
  deleteDocument: (id: string) => api.delete(`/files/${id}`),
  bulkDeleteDocuments: (fileIds: number[]) =>
    api.post('/files/bulk/delete', {
      file_ids: fileIds,
    }),
  retryDocument: (id: string) => api.post(`/files/${id}/retry`),
  getIngestJob: (jobId: string) => api.get(`/files/jobs/${jobId}`),
  downloadDocument: (id: string) =>
    api.get(`/file/download/${id}`, {
      responseType: 'blob',
    }),
  getDocumentMarkdown: (id: string) => api.get(`/files/${id}/markdown`),
  getDocumentPageImage: (fileId: number, pageNumber: number) =>
    api.get(`/files/${fileId}/pages/${pageNumber}/image`),
  getReasoningStages: () => api.get('/questions/reasoning/stages'),
  getGraphDefinition: () => api.get('/questions/graph/definition'),
  getScopeOptions: () => api.get<RAGScopeOptions>('/questions/scope-options'),
  chat: async (
    question: string,
    fileIds?: Array<string | number>,
    history?: Array<{ role: string; content: string }>,
    conversationId?: number,
    requestOptions?: ChatRequestOptions
  ) => {
    const normalizedFileIds = Array.isArray(fileIds)
      ? fileIds
          .map((value) => Number(value))
          .filter((value) => !Number.isNaN(value))
      : [];
    const payload: Record<string, any> = {
      question,
      file_ids: normalizedFileIds,
      allow_inferred_scope: requestOptions?.allow_inferred_scope ?? true,
      top_k: Number(requestOptions?.top_k ?? 5),
    };
    if (requestOptions?.candidate_k !== undefined) {
      payload.candidate_k = Number(requestOptions.candidate_k);
    }
    if (requestOptions?.min_pages_per_selected_doc !== undefined) {
      payload.min_pages_per_selected_doc = Number(requestOptions.min_pages_per_selected_doc);
    }
    if (requestOptions?.summary_mode) {
      payload.summary_mode = String(requestOptions.summary_mode);
    }
    if (requestOptions?.metadata_mode) {
      payload.metadata_mode = String(requestOptions.metadata_mode);
    }
    if (Array.isArray(requestOptions?.archive_slugs) && requestOptions.archive_slugs.length > 0) {
      payload.archive_slugs = requestOptions.archive_slugs;
    }
    if (Array.isArray(requestOptions?.metadata_fields) && requestOptions.metadata_fields.length > 0) {
      payload.metadata_fields = requestOptions.metadata_fields;
    }
    if (history && history.length > 0) {
      payload.history = history;
    }
    if (conversationId) {
      payload.conversation_id = Number(conversationId);
    }
    const resp = await api.post('/questions/ask', payload);
    const normalized = normalizeAskResponsePayload(resp.data || {});
    return {
      data: normalized,
    };
  },
  chatStream: async (
    question: string,
    fileIds?: Array<string | number>,
    history?: Array<{ role: string; content: string }>,
    conversationId?: number,
    requestOptions?: ChatRequestOptions,
    onGraphEvent?: (event: GraphRuntimeEvent) => void
  ) => {
    const normalizedFileIds = Array.isArray(fileIds)
      ? fileIds
          .map((value) => Number(value))
          .filter((value) => !Number.isNaN(value))
      : [];
    const payload: Record<string, any> = {
      question,
      file_ids: normalizedFileIds,
      allow_inferred_scope: requestOptions?.allow_inferred_scope ?? true,
      top_k: Number(requestOptions?.top_k ?? 5),
    };
    if (requestOptions?.candidate_k !== undefined) {
      payload.candidate_k = Number(requestOptions.candidate_k);
    }
    if (requestOptions?.min_pages_per_selected_doc !== undefined) {
      payload.min_pages_per_selected_doc = Number(requestOptions.min_pages_per_selected_doc);
    }
    if (requestOptions?.summary_mode) {
      payload.summary_mode = String(requestOptions.summary_mode);
    }
    if (requestOptions?.metadata_mode) {
      payload.metadata_mode = String(requestOptions.metadata_mode);
    }
    if (Array.isArray(requestOptions?.archive_slugs) && requestOptions.archive_slugs.length > 0) {
      payload.archive_slugs = requestOptions.archive_slugs;
    }
    if (Array.isArray(requestOptions?.metadata_fields) && requestOptions.metadata_fields.length > 0) {
      payload.metadata_fields = requestOptions.metadata_fields;
    }
    if (history && history.length > 0) {
      payload.history = history;
    }
    if (conversationId) {
      payload.conversation_id = Number(conversationId);
    }

    const token = localStorage.getItem('token');
    const response = await fetch(`${baseURL}/questions/ask/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const payload = await response.json();
        detail = String(payload?.detail || detail);
      } catch {
        // ignore JSON parse errors
      }
      throw new Error(detail);
    }
    if (!response.body) {
      throw new Error('Streaming response body is not available.');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let finalResponsePayload: Record<string, any> | null = null;

    const processSseBlock = (block: string) => {
      const lines = block.split('\n');
      let eventName = 'message';
      const dataLines: string[] = [];
      for (const line of lines) {
        if (line.startsWith('event:')) {
          eventName = line.slice('event:'.length).trim();
          continue;
        }
        if (line.startsWith('data:')) {
          dataLines.push(line.slice('data:'.length).trim());
        }
      }
      if (dataLines.length === 0) return;
      const dataString = dataLines.join('\n');
      let parsed: any = null;
      try {
        parsed = JSON.parse(dataString);
      } catch {
        parsed = { raw: dataString };
      }
      if (eventName === 'error') {
        throw new Error(String(parsed?.detail || parsed?.error || 'Streaming chat failed.'));
      }
      if (eventName === 'graph_event') {
        const graphEvent = parsed as GraphRuntimeEvent;
        onGraphEvent?.(graphEvent);
        if (graphEvent?.event_type === 'run_completed' && graphEvent?.final_response) {
          finalResponsePayload = graphEvent.final_response;
        }
      }
    };

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let separatorIndex = buffer.indexOf('\n\n');
        while (separatorIndex !== -1) {
          const block = buffer.slice(0, separatorIndex).trim();
          buffer = buffer.slice(separatorIndex + 2);
          if (block) {
            processSseBlock(block);
          }
          separatorIndex = buffer.indexOf('\n\n');
        }
      }
      const tail = buffer.trim();
      if (tail) {
        processSseBlock(tail);
      }
    } finally {
      reader.releaseLock();
    }

    if (!finalResponsePayload) {
      throw new Error('Streaming finished without final response payload.');
    }
    return {
      data: normalizeAskResponsePayload(finalResponsePayload),
    };
  },
};

export const metadataApi = {
  listUploads: (params?: { includeArchived?: boolean; search?: string }) =>
    api.get<MetadataUploadListResponse>('/metadata/uploads', {
      params: {
        include_archived: params?.includeArchived ?? true,
        ...(params?.search ? { search: params.search } : {}),
      },
    }),
  getUpload: (metadataUploadId: string, rowLimit: number = 100) =>
    api.get<MetadataUploadDetailResponse>(`/metadata/uploads/${metadataUploadId}`, {
      params: { row_limit: rowLimit },
    }),
  uploadCsv: (
    file: File,
    displayName?: string,
    description?: string,
    accessScope: 'private' | 'all' = 'private'
  ) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('access_scope', accessScope);
    if (displayName !== undefined) {
      formData.append('display_name', displayName);
    }
    if (description !== undefined) {
      formData.append('description', description);
    }
    return api.post<MetadataUploadResponse>('/metadata/upload', formData);
  },
  updateUpload: (metadataUploadId: string, payload: MetadataUploadUpdateRequest) =>
    api.patch<MetadataUploadSummary>(`/metadata/uploads/${metadataUploadId}`, payload),
  replaceCsv: (metadataUploadId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.put<MetadataUploadResponse>(`/metadata/uploads/${metadataUploadId}/file`, formData);
  },
  deleteUpload: (metadataUploadId: string) => api.delete(`/metadata/uploads/${metadataUploadId}`),
};

export const chatApi = {
  listConversations: (search?: string) =>
    api.get('/chats', {
      params: search ? { search } : undefined,
    }),
  createConversation: (title?: string) => api.post('/chats', { title }),
  renameConversation: (conversationId: number, title: string) =>
    api.patch(`/chats/${conversationId}`, { title }),
  deleteConversation: (conversationId: number) => api.delete(`/chats/${conversationId}`),
  getMessages: (conversationId: number) => api.get(`/chats/${conversationId}/messages`),
  exportConversation: (conversationId: number, format: 'markdown' | 'json' = 'markdown') =>
    api.get(`/chats/${conversationId}/export`, {
      params: { format },
      responseType: format === 'markdown' ? 'blob' : 'json',
    }),
};

export const settingsApi = {
  getPublic: () => api.get('/settings/public'),
  get: () => api.get('/settings'),
  update: (updates: any) => api.put('/settings', { updates }),
  uploadAgentAvatar: (file: File) => {
    const payload = new FormData();
    payload.append('file', file);
    return api.post('/settings/agent-avatar', payload);
  },
  deleteAgentAvatar: () => api.delete('/settings/agent-avatar'),
};

export const profilesApi = {
  list: () =>
    Promise.resolve({
      data: {
        profiles: [
          { id: 'all', name: 'All' },
          { id: 'private', name: 'Private' },
        ],
      },
    }),
};

export default api;
