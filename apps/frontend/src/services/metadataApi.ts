import api from './apiClient';
import type {
  MetadataUploadDetailResponse,
  MetadataUploadListResponse,
  MetadataUploadResponse,
  MetadataUploadSummary,
  MetadataUploadUpdateRequest,
} from './apiTypes';

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
