type RAGReplaceConfirmModalProps = {
  duplicateDocs: any[];
  processPending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

export function RAGReplaceConfirmModal({
  duplicateDocs,
  processPending,
  onCancel,
  onConfirm,
}: RAGReplaceConfirmModalProps) {
  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white rounded-lg w-full max-w-md max-h-[min(80vh,720px)] overflow-hidden">
        <div className="p-6 flex min-h-0 flex-1 flex-col">
          <h2 className="text-lg font-bold text-oracle-dark-gray mb-2">Document already exists</h2>
          <p className="text-sm text-oracle-medium-gray mb-4">
            A document with this name already exists ({duplicateDocs.length}):
          </p>
          <ul className="list-disc list-inside text-sm text-oracle-dark-gray mb-4 max-h-72 overflow-y-auto pr-2">
            {duplicateDocs.map((doc: any) => (
              <li key={doc.id}>{doc.original_name || doc.filename}</li>
            ))}
          </ul>
          <p className="text-sm text-oracle-medium-gray">
            Do you want to reprocess it? The existing document will be deleted and processed again.
          </p>
          <div className="mt-4 flex gap-2 justify-end border-t border-gray-100 pt-4">
            <button
              type="button"
              onClick={onCancel}
              className="btn-secondary"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={onConfirm}
              disabled={processPending}
              className="btn-primary"
            >
              {processPending ? 'Processing...' : 'Yes, reprocess'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
