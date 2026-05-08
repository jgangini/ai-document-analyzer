import type { ImprovementCheckpointThread } from '../../../services/apiTypes';
import { formatDateTime } from './Improvement.model';

type ImprovementCheckpointsTabProps = {
  checkpoints: ImprovementCheckpointThread[];
  paginatedCheckpoints: ImprovementCheckpointThread[];
  startIndex: number;
  endIndex: number;
  currentPage: number;
  totalPages: number;
  onPageChange: (updater: (page: number) => number) => void;
  onOpenTrace: (traceId: string) => void;
};

export function ImprovementCheckpointsTab({
  checkpoints,
  paginatedCheckpoints,
  startIndex,
  endIndex,
  currentPage,
  totalPages,
  onPageChange,
  onOpenTrace,
}: ImprovementCheckpointsTabProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="app-scrollbar min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        <table className="min-w-full table-fixed text-left text-sm">
          <thead className="sticky top-0 bg-gray-50 text-xs uppercase tracking-wide text-oracle-light-gray">
            <tr>
              <th className="w-[260px] px-4 py-3">Thread</th>
              <th className="px-4 py-3">Latest question</th>
              <th className="w-28 px-4 py-3">Snapshots</th>
              <th className="w-24 px-4 py-3">Writes</th>
              <th className="w-24 px-4 py-3">Traces</th>
              <th className="w-44 px-4 py-3">Updated</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {paginatedCheckpoints.map((checkpoint) => (
              <tr key={checkpoint.thread_id} className="hover:bg-gray-50">
                <td className="px-4 py-3">
                  <p className="truncate text-xs font-semibold text-oracle-dark-gray">{checkpoint.thread_id}</p>
                  {checkpoint.latest_trace_id ? (
                    <button
                      type="button"
                      className="mt-1 text-xs font-semibold text-oracle-red hover:underline"
                      onClick={() => onOpenTrace(checkpoint.latest_trace_id)}
                    >
                      View latest trace
                    </button>
                  ) : null}
                </td>
                <td className="px-4 py-3">
                  <p className="line-clamp-2 text-sm text-oracle-dark-gray">{checkpoint.latest_question || '-'}</p>
                </td>
                <td className="px-4 py-3 text-sm font-semibold text-oracle-dark-gray">{checkpoint.checkpoint_count}</td>
                <td className="px-4 py-3 text-sm font-semibold text-oracle-dark-gray">{checkpoint.write_count}</td>
                <td className="px-4 py-3 text-sm font-semibold text-oracle-dark-gray">{checkpoint.trace_count}</td>
                <td className="whitespace-nowrap px-4 py-3 text-xs text-oracle-medium-gray">
                  {formatDateTime(checkpoint.updated_at)}
                </td>
              </tr>
            ))}
            {checkpoints.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-sm text-oracle-light-gray">
                  No checkpoints recorded yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      {checkpoints.length > 0 ? (
        <div className="flex shrink-0 items-center justify-between border-t border-gray-200 px-4 py-3">
          <p className="text-sm text-gray-600">
            Showing {startIndex + 1}-{endIndex} of {checkpoints.length}
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onPageChange((page) => Math.max(1, page - 1))}
              disabled={currentPage <= 1}
              className="rounded border border-gray-300 bg-white px-3 py-1 text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Previous
            </button>
            <span className="text-sm text-gray-600">
              Page {currentPage} of {totalPages}
            </span>
            <button
              type="button"
              onClick={() => onPageChange((page) => Math.min(totalPages, page + 1))}
              disabled={currentPage >= totalPages}
              className="rounded border border-gray-300 bg-white px-3 py-1 text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
