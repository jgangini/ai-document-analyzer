import api, { baseURL } from './apiClient';
import type {
  ChatRequestOptions,
  ChatSource,
  GraphRuntimeEvent,
  MetadataUploadResponse,
  RAGScopeOptions,
  ReasoningResult,
  UploadPreparationGroup,
  UploadPreparationResponse,
} from './apiTypes';

function normalizeSourceItems(sourceItems: any[], evidenceBySource: Map<number, any>): ChatSource[] {
  return sourceItems.map((item: any, index: number) => {
    const sourceNumber = Number(item?.source_number ?? item?.doc_id ?? 0);
    const matchedEvidence = evidenceBySource.get(sourceNumber);
    const fileName = String(item?.file_name || '').trim();
    const pageNumber = Number(item?.page_number ?? matchedEvidence?.page_number ?? 0);
    const sourceName = String(item?.name || '').trim();
    const snippet = String(item?.snippet ?? matchedEvidence?.summary_text ?? '').trim();
    return {
      doc_id: String(item?.doc_id || item?.source_number || index + 1),
      name: sourceName || `${fileName || 'document'} - page ${pageNumber || '?'}`,
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
  const citedSources: ChatSource[] = Array.isArray(data?.cited_sources)
    ? normalizeSourceItems(data.cited_sources, evidenceBySource)
    : [];
  return {
    success: true,
    reply: data?.answer || data?.answer_text || '',
    citedSources,
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
