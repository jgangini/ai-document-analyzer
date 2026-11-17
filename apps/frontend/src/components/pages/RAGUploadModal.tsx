import type { ChangeEvent, DragEvent, ReactNode } from 'react';

import type { MetadataUploadSummary } from '../../services/apiTypes';
import { LoadingState } from '../common/LoadingState';
import { ModalPortal } from '../common/ModalPortal';
import {
  uploadDraftActionButtonClassName,
  uploadDraftMetadataSelectClassName,
} from './RAG.model';

type RAGUploadModalProps = {
  children: ReactNode;
  preparedUploadsSummary: string;
  selectedMetadataUploadId: string;
  selectedMetadataUpload: MetadataUploadSummary | null;
  selectedMetadataLabel: string;
  metadataUploads: MetadataUploadSummary[];
  metadataUploadsLoading: boolean;
  hasPreparedUploads: boolean;
  preparePending: boolean;
  processPending: boolean;
  uploadDraftFilter: string;
  isDragging: boolean;
  totalPreparedItems: number;
  metadataMatchedPreparedItems: number;
  hasMetadataSelection: boolean;
  canProcessUploadDraft: boolean;
  onClose: () => void;
  onFileSelect: (event: ChangeEvent<HTMLInputElement>) => void;
  onMetadataSelect: (metadataUploadId: string) => void;
  onUploadDraftFilterChange: (value: string) => void;
  onClearUploadDraftFilter: () => void;
  onDragOver: (event: DragEvent) => void;
  onDragLeave: (event: DragEvent) => void;
  onDrop: (event: DragEvent) => void;
  onSubmit: () => void;
};

export function RAGUploadModal({
  children,
  preparedUploadsSummary,
  selectedMetadataUploadId,
  selectedMetadataUpload,
  selectedMetadataLabel,
  metadataUploads,
  metadataUploadsLoading,
  hasPreparedUploads,
  preparePending,
  processPending,
  uploadDraftFilter,
  isDragging,
  totalPreparedItems,
  metadataMatchedPreparedItems,
  hasMetadataSelection,
  canProcessUploadDraft,
  onClose,
  onFileSelect,
  onMetadataSelect,
  onUploadDraftFilterChange,
  onClearUploadDraftFilter,
  onDragOver,
  onDragLeave,
  onDrop,
  onSubmit,
}: RAGUploadModalProps) {
  return (
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
                onClick={onClose}
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
            onChange={onFileSelect}
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
                    onChange={(event) => onMetadataSelect(event.target.value)}
                    disabled={metadataUploadsLoading}
                    className={uploadDraftMetadataSelectClassName}
                    title="Select an existing metadata dataset"
                  >
                    <option value="">
                      {metadataUploadsLoading ? 'Loading metadata...' : 'Select metadata...'}
                    </option>
                    {metadataUploads.map((dataset: MetadataUploadSummary) => (
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
                      onChange={(event) => onUploadDraftFilterChange(event.target.value)}
                      placeholder="Filter by folder or document..."
                      className="input-oracle w-full pr-10"
                    />
                    {uploadDraftFilter && (
                      <button
                        type="button"
                        onClick={onClearUploadDraftFilter}
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
              preparePending ? (
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
                    onDragEnter={onDragOver}
                    onDragLeave={onDragLeave}
                    onDragOver={onDragOver}
                    onDrop={onDrop}
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
            ) : children}
          </div>

          <div className="flex shrink-0 gap-3 justify-end pt-2">
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button
              type="button"
              onClick={onSubmit}
              disabled={!canProcessUploadDraft}
              className="btn-primary"
            >
              {processPending ? 'Processing...' : preparePending ? 'Preparing...' : 'Process files'}
            </button>
          </div>
        </div>
      </div>
    </ModalPortal>
  );
}
