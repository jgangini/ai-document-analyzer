type RAGQueueSummaryProps = {
  queue: {
    pending?: number;
    processing_ocr?: number;
    error?: number;
    completed?: number;
  };
};

export function RAGQueueSummary({ queue }: RAGQueueSummaryProps) {
  return (
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
  );
}
