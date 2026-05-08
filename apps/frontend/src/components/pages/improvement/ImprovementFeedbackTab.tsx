import type { ImprovementFeedbackEvent } from '../../../services/apiTypes';
import { StatusPill } from './ImprovementBadges';
import { formatDateTime } from './Improvement.model';

type ImprovementFeedbackTabProps = {
  feedback: ImprovementFeedbackEvent[];
};

export function ImprovementFeedbackTab({ feedback }: ImprovementFeedbackTabProps) {
  return (
    <div className="app-scrollbar min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
      <table className="min-w-full table-fixed text-left text-sm">
        <thead className="sticky top-0 bg-gray-50 text-xs uppercase tracking-wide text-oracle-light-gray">
          <tr>
            <th className="w-44 px-4 py-3">Time</th>
            <th className="w-32 px-4 py-3">Signal</th>
            <th className="px-4 py-3">Prompt</th>
            <th className="px-4 py-3">Answer</th>
            <th className="w-32 px-4 py-3">Trace</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {feedback.map((event) => (
            <tr key={event.feedback_event_id} className="hover:bg-gray-50">
              <td className="whitespace-nowrap px-4 py-3 text-xs text-oracle-medium-gray">
                {formatDateTime(event.created_at)}
              </td>
              <td className="px-4 py-3">
                <StatusPill value={`${event.event_type}:${event.value}`} />
              </td>
              <td className="px-4 py-3">
                <p className="line-clamp-3 text-sm text-oracle-dark-gray">{event.user_prompt || '-'}</p>
              </td>
              <td className="px-4 py-3">
                <p className="line-clamp-3 text-xs leading-5 text-oracle-medium-gray">
                  {event.assistant_answer_preview || '-'}
                </p>
              </td>
              <td className="px-4 py-3 text-xs text-oracle-light-gray">{event.trace_id || '-'}</td>
            </tr>
          ))}
          {feedback.length === 0 ? (
            <tr>
              <td colSpan={5} className="px-4 py-10 text-center text-sm text-oracle-light-gray">
                No feedback events recorded yet.
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
