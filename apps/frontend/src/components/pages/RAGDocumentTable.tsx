import type { RefObject } from 'react';

import { LoadingState } from '../common/LoadingState';
import { getDocumentDisplayParts } from './RAG.model';

type RAGDocumentTableProps = {
  documents: any[];
  isLoading: boolean;
  searchTerm: string;
  isAdmin: boolean;
  selectedDocumentIdSet: Set<number>;
  allCurrentPageDocumentsSelected: boolean;
  selectAllDocumentsRef: RefObject<HTMLInputElement>;
  deletePending: boolean;
  retryPending: boolean;
  totalDocuments: number;
  startIndex: number;
  endIndex: number;
  currentPage: number;
  totalPages: number;
  onToggleDocumentSelection: (documentId: number, selected: boolean) => void;
  onToggleAllVisibleDocuments: (selected: boolean) => void;
  onViewDocument: (document: any) => void;
  onDownloadDocument: (document: any) => void;
  onEditDocument: (document: any) => void;
  onRetryDocument: (document: any) => void;
  onDeleteDocument: (document: any) => void;
  onPreviousPage: () => void;
  onNextPage: () => void;
};

function highlightText(text: string | undefined, search: string) {
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

function getStatusBadge(status: string) {
  const classes: Record<string, string> = {
    completed:
      'inline-flex items-center rounded-xl border border-emerald-200 bg-emerald-50/60 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-emerald-700',
    pending:
      'inline-flex items-center rounded-xl border border-amber-200 bg-amber-50/60 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-amber-700',
    processing_ocr:
      'inline-flex items-center rounded-xl border border-blue-200 bg-blue-50/60 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-blue-700',
    vectorizing:
      'inline-flex items-center rounded-xl border border-purple-200 bg-purple-50/60 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-purple-700',
    error:
      'inline-flex items-center rounded-xl border border-rose-200 bg-rose-50/60 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-rose-700',
  };
  return (
    classes[status] ||
    'inline-flex items-center rounded-xl border border-gray-200 bg-gray-50 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-gray-700'
  );
}

function getStatusLabel(status: string) {
  const labels: Record<string, string> = {
    completed: 'Completed',
    pending: 'Pending',
    processing_ocr: 'OCR',
    vectorizing: 'Vectorizing',
    error: 'Error',
  };
  return labels[status] || String(status || '');
}

function getAccessLabel(accessValue: string) {
  const normalized = String(accessValue || '').trim().toLowerCase();
  if (normalized === 'private') return 'Private';
  if (normalized === 'all') return 'All Users';
  return normalized
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function formatCreatedAt(value: string | undefined) {
  if (!value) return '-';
  const date = new Date(value);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(date.getDate())}-${pad(date.getMonth() + 1)}-${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function RAGDocumentTable({
  documents,
  isLoading,
  searchTerm,
  isAdmin,
  selectedDocumentIdSet,
  allCurrentPageDocumentsSelected,
  selectAllDocumentsRef,
  deletePending,
  retryPending,
  totalDocuments,
  startIndex,
  endIndex,
  currentPage,
  totalPages,
  onToggleDocumentSelection,
  onToggleAllVisibleDocuments,
  onViewDocument,
  onDownloadDocument,
  onEditDocument,
  onRetryDocument,
  onDeleteDocument,
  onPreviousPage,
  onNextPage,
}: RAGDocumentTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200/70 bg-white">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="w-12 px-4 py-3 text-center">
              <input
                ref={selectAllDocumentsRef}
                type="checkbox"
                checked={allCurrentPageDocumentsSelected}
                onChange={(event) => onToggleAllVisibleDocuments(event.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-oracle-red accent-oracle-red focus:ring-oracle-red"
                aria-label="Select all documents on the current page"
              />
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Document</th>
            <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">Pages</th>
            <th className="w-28 min-w-[7rem] px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Access</th>
            <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider w-[180px] min-w-[180px]">
              Created
            </th>
            <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider w-24">Status</th>
            <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider w-28">Actions</th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {isLoading ? (
            <tr>
              <td colSpan={7} className="px-4 py-8">
                <LoadingState size="sm" />
              </td>
            </tr>
          ) : documents.length === 0 ? (
            <tr>
              <td colSpan={7} className="px-4 py-8 text-center text-oracle-light-gray">
                No documents found
              </td>
            </tr>
          ) : (
            documents.map((document) => {
              const { folder, fileName } = getDocumentDisplayParts(document);
              return (
                <tr key={document.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-center align-top">
                    <input
                      type="checkbox"
                      checked={selectedDocumentIdSet.has(Number(document.id))}
                      onChange={(event) => onToggleDocumentSelection(Number(document.id), event.target.checked)}
                      className="mt-1 h-4 w-4 rounded border-gray-300 text-oracle-red accent-oracle-red focus:ring-oracle-red"
                      aria-label={`Select ${document.original_name || document.filename || 'document'}`}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center">
                      <div className="min-w-0 flex flex-wrap items-center gap-0.5">
                        {folder && (
                          <div className="flex items-center gap-0.5 min-w-0 shrink-0">
                            <span className="text-xs bg-oracle-bg-gray px-1.5 py-0.5 rounded">
                              {highlightText(folder, searchTerm)}
                            </span>
                            <span className="text-xs text-oracle-light-gray">/</span>
                          </div>
                        )}
                        <span className="inline-block w-fit text-xs bg-oracle-bg-gray px-1.5 py-0.5 rounded truncate max-w-xs">
                          {highlightText(fileName, searchTerm)}
                        </span>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-sm text-oracle-medium-gray text-center">{document.pages || '-'}</td>
                  <td className="w-28 min-w-[7rem] px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {document.access_profiles?.map((profile: string, index: number) => (
                        <span key={index} className="whitespace-nowrap text-xs bg-oracle-bg-gray px-1.5 py-0.5 rounded">
                          {getAccessLabel(profile)}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-sm text-oracle-light-gray text-center w-[180px] min-w-[180px]">
                    {formatCreatedAt(document.created_at)}
                  </td>
                  <td className="px-4 py-3 text-center w-24">
                    <span className={getStatusBadge(document.status)}>{getStatusLabel(document.status)}</span>
                  </td>
                  <td className="px-4 py-3 text-right w-28">
                    <div className="flex justify-end gap-1">
                      {document.status === 'completed' && (
                        <button
                          type="button"
                          onClick={() => onViewDocument(document)}
                          className="p-1.5 rounded border border-gray-300 bg-white text-gray-600 hover:bg-gray-50 transition-colors"
                          title="View PDF & Markdown"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                          </svg>
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => onDownloadDocument(document)}
                        className="p-1.5 rounded border border-gray-300 bg-white text-gray-600 hover:bg-gray-50 transition-colors"
                        title="Download"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                      </button>
                      {isAdmin && (
                        <button
                          type="button"
                          onClick={() => onEditDocument(document)}
                          className="p-1.5 rounded border border-gray-300 bg-white text-gray-600 hover:bg-gray-50 transition-colors"
                          title="Edit"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                          </svg>
                        </button>
                      )}
                      {document.status === 'error' && isAdmin && (
                        <button
                          type="button"
                          onClick={() => onRetryDocument(document)}
                          className="p-1.5 rounded border border-gray-300 bg-white text-gray-600 hover:bg-gray-50 transition-colors"
                          disabled={retryPending}
                          title="Retry"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                          </svg>
                        </button>
                      )}
                      {isAdmin && (
                        <button
                          type="button"
                          onClick={() => onDeleteDocument(document)}
                          className="p-1.5 rounded border border-red-300 bg-white text-red-600 hover:bg-red-50 transition-colors"
                          disabled={deletePending}
                          title="Delete"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>

      {totalDocuments > 0 && (
        <div className="mt-4 flex items-center justify-between border-t border-gray-200 px-4 py-3">
          <p className="text-sm text-gray-600">
            Showing {startIndex + 1}-{Math.min(endIndex, totalDocuments)} of {totalDocuments}
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onPreviousPage}
              disabled={currentPage === 1}
              className="px-3 py-1 text-sm border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Previous
            </button>
            <span className="text-sm text-gray-600">
              Page {currentPage} of {totalPages}
            </span>
            <button
              type="button"
              onClick={onNextPage}
              disabled={currentPage === totalPages}
              className="px-3 py-1 text-sm border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
