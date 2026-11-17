import type {
  ImprovementEvalCase,
  ImprovementEvalResult,
  ImprovementEvalRun,
} from '../../../services/apiTypes';
import { LoadingState } from '../../common/LoadingState';
import { StatusPill } from './ImprovementBadges';
import { formatEvalCategory, formatPercent } from './Improvement.model';

type ImprovementEvalsTabProps = {
  evalCases: ImprovementEvalCase[];
  paginatedEvalCases: ImprovementEvalCase[];
  selectedCaseIds: number[];
  startIndex: number;
  endIndex: number;
  currentPage: number;
  totalPages: number;
  runPending: boolean;
  evalRuns: ImprovementEvalRun[];
  selectedEvalRunId: number | null;
  evalResults: ImprovementEvalResult[];
  evalResultsLoading: boolean;
  onToggleCase: (evalCase: ImprovementEvalCase) => void;
  onOpenCreateCase: () => void;
  onRunSelected: () => void;
  onPageChange: (updater: (page: number) => number) => void;
  onSelectRun: (runId: number) => void;
  onOpenTrace: (traceId: string) => void;
};

export function ImprovementEvalsTab({
  evalCases,
  paginatedEvalCases,
  selectedCaseIds,
  startIndex,
  endIndex,
  currentPage,
  totalPages,
  runPending,
  evalRuns,
  selectedEvalRunId,
  evalResults,
  evalResultsLoading,
  onToggleCase,
  onOpenCreateCase,
  onRunSelected,
  onPageChange,
  onSelectRun,
  onOpenTrace,
}: ImprovementEvalsTabProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-oracle-border px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-oracle-dark-gray">Evaluation cases</p>
          <p className="text-xs text-oracle-light-gray">{selectedCaseIds.length} selected</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="btn-primary" onClick={onOpenCreateCase}>
            + Eval
          </button>
          <button
            type="button"
            className="btn-secondary"
            disabled={selectedCaseIds.length === 0 || runPending}
            onClick={onRunSelected}
          >
            {runPending ? 'Running...' : 'Run selected'}
          </button>
        </div>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_470px]">
        <div className="flex min-h-0 min-w-0 flex-col">
          <div className="app-scrollbar min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
            <table className="min-w-full text-left text-sm">
              <thead className="sticky top-0 bg-gray-50 text-xs uppercase tracking-wide text-oracle-light-gray">
                <tr>
                  <th className="w-12 px-4 py-3"></th>
                  <th className="px-4 py-3">Case</th>
                  <th className="w-32 px-4 py-3">Category</th>
                  <th className="w-32 px-4 py-3">Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {paginatedEvalCases.map((evalCase) => (
                  <tr key={evalCase.eval_case_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        aria-label={`Select ${evalCase.name}`}
                        checked={selectedCaseIds.includes(evalCase.eval_case_id)}
                        onChange={() => onToggleCase(evalCase)}
                        className="h-4 w-4 rounded border-gray-300 text-oracle-red accent-oracle-red focus:ring-oracle-red"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-medium text-oracle-dark-gray">{evalCase.name}</p>
                      <p className="mt-1 line-clamp-2 text-xs text-oracle-medium-gray">{evalCase.question}</p>
                    </td>
                    <td className="px-4 py-3 text-xs text-oracle-medium-gray">
                      {formatEvalCategory(evalCase.category)}
                    </td>
                    <td className="px-4 py-3 text-xs text-oracle-medium-gray">{evalCase.source}</td>
                  </tr>
                ))}
                {evalCases.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-10 text-center text-sm text-oracle-light-gray">
                      No evaluation cases recorded yet.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          {evalCases.length > 0 ? (
            <div className="flex shrink-0 items-center justify-between border-t border-gray-200 px-4 py-3">
              <p className="text-sm text-gray-600">
                Showing {startIndex + 1}-{endIndex} of {evalCases.length}
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
        <div className="flex min-w-0 min-h-0 flex-col border-l border-oracle-border">
          <div className="shrink-0 border-b border-oracle-border bg-gray-50 px-4 py-3">
            <p className="text-sm font-semibold text-oracle-dark-gray">Recent runs</p>
            <p className="text-xs text-oracle-light-gray">Select a run to inspect results and traces.</p>
          </div>
          <div className="app-scrollbar max-h-[250px] shrink-0 divide-y divide-gray-100 overflow-auto">
            {evalRuns.map((run) => (
              <button
                key={run.eval_run_id}
                type="button"
                className={`block w-full px-4 py-3 text-left transition hover:bg-gray-50 ${
                  selectedEvalRunId === run.eval_run_id ? 'bg-amber-50/70' : ''
                }`}
                onClick={() => onSelectRun(run.eval_run_id)}
              >
                <div className="flex items-center justify-between gap-3">
                  <p className="truncate text-sm font-medium text-oracle-dark-gray">{run.name}</p>
                  <StatusPill value={run.status} />
                </div>
                <p className="mt-1 text-xs text-oracle-light-gray">
                  {run.result_count} results - score {formatPercent(run.avg_score || 0)}
                </p>
              </button>
            ))}
            {evalRuns.length === 0 ? (
              <div className="px-4 py-8 text-sm text-oracle-light-gray">No evaluation runs recorded yet.</div>
            ) : null}
          </div>
          <div className="shrink-0 border-t border-oracle-border px-4 py-3">
            <p className="text-sm font-semibold text-oracle-dark-gray">Results</p>
            <p className="text-xs text-oracle-light-gray">
              {selectedEvalRunId ? `Run #${selectedEvalRunId}` : 'No run selected'}
            </p>
          </div>
          <div className="app-scrollbar min-h-0 flex-1 space-y-2 overflow-auto px-4 pb-4">
            {!selectedEvalRunId ? (
              <div className="rounded-lg border border-dashed border-gray-300 px-3 py-6 text-center text-sm text-oracle-light-gray">
                Select a run to audit its answers.
              </div>
            ) : evalResultsLoading ? (
              <LoadingState className="py-6" size="sm" label="Loading eval results..." textClassName="text-oracle-light-gray" />
            ) : (
              evalResults.map((result) => (
                <div key={result.eval_result_id} className="rounded-lg border border-gray-200 bg-white px-3 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <p className="min-w-0 truncate text-sm font-semibold text-oracle-dark-gray">{result.case_name}</p>
                    <StatusPill value={result.status} />
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs text-oracle-medium-gray">{result.question}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-oracle-light-gray">
                    <span>Score {formatPercent(result.score || 0)}</span>
                    {result.trace_id ? (
                      <button
                        type="button"
                        className="font-semibold text-oracle-red hover:underline"
                        onClick={() => onOpenTrace(result.trace_id)}
                      >
                        View trace
                      </button>
                    ) : null}
                  </div>
                </div>
              ))
            )}
            {selectedEvalRunId && !evalResultsLoading && evalResults.length === 0 ? (
              <div className="rounded-lg border border-dashed border-gray-300 px-3 py-6 text-center text-sm text-oracle-light-gray">
                This run has no recorded results.
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
