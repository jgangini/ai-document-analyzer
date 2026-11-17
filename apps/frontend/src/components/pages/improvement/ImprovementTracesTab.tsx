import type { ImprovementTraceRun, ImprovementTraceStep } from '../../../services/apiTypes';
import { LoadingState } from '../../common/LoadingState';
import { StatusPill } from './ImprovementBadges';
import { compactJson, formatDateTime } from './Improvement.model';

type ImprovementTracesTabProps = {
  traces: ImprovementTraceRun[];
  selectedTrace: ImprovementTraceRun | null;
  selectedTraceId: string;
  traceSteps: ImprovementTraceStep[];
  loadingTraceSteps: boolean;
  onSelectTrace: (traceId: string) => void;
};

export function ImprovementTracesTab({
  traces,
  selectedTrace,
  selectedTraceId,
  traceSteps,
  loadingTraceSteps,
  onSelectTrace,
}: ImprovementTracesTabProps) {
  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1.1fr)_minmax(440px,0.9fr)]">
      <div className="flex min-w-0 min-h-0 flex-col border-r border-oracle-border">
        <div className="app-scrollbar min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
          <table className="min-w-full table-fixed text-left text-sm">
            <thead className="sticky top-0 z-10 bg-gray-50 text-xs uppercase tracking-wide text-oracle-light-gray">
              <tr>
                <th className="w-44 px-4 py-3">Time</th>
                <th className="px-4 py-3">Question</th>
                <th className="w-[160px] px-4 py-3">Route</th>
                <th className="w-[118px] px-4 py-3">Status</th>
                <th className="w-[88px] px-4 py-3">Cites</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {traces.map((trace) => (
                <tr
                  key={trace.trace_id}
                  className={`cursor-pointer transition hover:bg-gray-50 ${
                    selectedTraceId === trace.trace_id ? 'bg-amber-50/70' : ''
                  }`}
                  onClick={() => onSelectTrace(trace.trace_id)}
                >
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-oracle-medium-gray">
                    {formatDateTime(trace.started_at)}
                  </td>
                  <td className="px-4 py-3">
                    <p className="line-clamp-2 font-medium text-oracle-dark-gray">{trace.question}</p>
                    <p className="mt-1 truncate text-xs text-oracle-light-gray">{trace.thread_id}</p>
                  </td>
                  <td className="px-4 py-3 text-xs font-medium text-oracle-medium-gray">
                    {trace.answerability_route || 'unclassified'}
                  </td>
                  <td className="px-4 py-3">
                    <StatusPill value={trace.status} />
                  </td>
                  <td className="px-4 py-3 text-sm font-semibold text-oracle-dark-gray">{trace.cited_sources_count}</td>
                </tr>
              ))}
              {traces.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-sm text-oracle-light-gray">
                    No trace runs recorded yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
      <div className="flex min-w-0 min-h-0 flex-col">
        <div className="shrink-0 border-b border-oracle-border px-4 py-3">
          <p className="text-sm font-semibold text-oracle-dark-gray">
            {selectedTrace ? selectedTrace.question : 'Trace detail'}
          </p>
          {selectedTrace ? (
            <p className="mt-1 text-xs text-oracle-light-gray">
              {selectedTrace.trace_id} - {selectedTrace.answerability_route || 'unclassified'}
            </p>
          ) : null}
        </div>
        <div className="app-scrollbar min-h-0 flex-1 overflow-auto p-4">
          {!selectedTraceId ? (
            <div className="rounded-lg border border-dashed border-gray-300 px-4 py-10 text-center text-sm text-oracle-light-gray">
              Select a trace to inspect graph steps.
            </div>
          ) : loadingTraceSteps ? (
            <LoadingState className="py-8" size="sm" label="Loading trace steps..." textClassName="text-oracle-light-gray" />
          ) : (
            <div className="space-y-3">
              {traceSteps.map((step) => (
                <details key={step.step_id} className="rounded-lg border border-gray-200 bg-white px-3 py-2">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
                    <span className="min-w-0 truncate text-sm font-semibold text-oracle-dark-gray">
                      {step.node || step.status}
                    </span>
                    <span className="shrink-0 text-xs text-oracle-light-gray">{step.duration_ms || 0} ms</span>
                  </summary>
                  <pre className="app-scrollbar mt-2 max-h-72 overflow-auto rounded bg-gray-50 p-3 text-[11px] leading-5 text-oracle-medium-gray">
                    {compactJson({ payload: step.payload, state_patch: step.state_patch, error: step.error })}
                  </pre>
                </details>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
