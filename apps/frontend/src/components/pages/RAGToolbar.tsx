import { documentToolbarButtonClassName } from './RAG.model';

type RAGToolbarProps = {
  searchTerm: string;
  statusFilter: string;
  isAdmin: boolean;
  isLoading: boolean;
  selectedCount: number;
  editPending: boolean;
  deletePending: boolean;
  onSearchChange: (value: string) => void;
  onStatusChange: (value: string) => void;
  onRefresh: () => void;
  onBulkEdit: () => void;
  onBulkDelete: () => void;
};

export function RAGToolbar({
  searchTerm,
  statusFilter,
  isAdmin,
  isLoading,
  selectedCount,
  editPending,
  deletePending,
  onSearchChange,
  onStatusChange,
  onRefresh,
  onBulkEdit,
  onBulkDelete,
}: RAGToolbarProps) {
  return (
    <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
      <div className="grid flex-1 grid-cols-1 gap-3 md:grid-cols-[1fr_150px]">
        <input
          type="text"
          value={searchTerm}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Search by filename..."
          className="input-oracle"
        />
        <select
          value={statusFilter}
          onChange={(event) => onStatusChange(event.target.value)}
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
          onClick={onRefresh}
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
              onClick={onBulkEdit}
              disabled={selectedCount === 0 || editPending}
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
              onClick={onBulkDelete}
              disabled={selectedCount === 0 || deletePending}
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
  );
}
