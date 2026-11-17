import { ModalPortal } from '../../common/ModalPortal';
import { EVAL_CATEGORY_OPTIONS } from './Improvement.model';

type CreateEvalCaseModalProps = {
  caseName: string;
  caseCategory: string;
  caseQuestion: string;
  caseTerms: string;
  minimumCitations: number;
  canSave: boolean;
  saving: boolean;
  onCaseNameChange: (value: string) => void;
  onCaseCategoryChange: (value: string) => void;
  onCaseQuestionChange: (value: string) => void;
  onCaseTermsChange: (value: string) => void;
  onMinimumCitationsChange: (value: number) => void;
  onClose: () => void;
  onSave: () => void;
};

export function CreateEvalCaseModal({
  caseName,
  caseCategory,
  caseQuestion,
  caseTerms,
  minimumCitations,
  canSave,
  saving,
  onCaseNameChange,
  onCaseCategoryChange,
  onCaseQuestionChange,
  onCaseTermsChange,
  onMinimumCitationsChange,
  onClose,
  onSave,
}: CreateEvalCaseModalProps) {
  return (
    <ModalPortal zIndex="z-[300]" className="items-start justify-center p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-eval-case-title"
        className="flex max-h-[min(720px,calc(100vh-2rem))] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border-0 shadow-2xl"
        style={{
          background: 'rgba(255,255,255,0.72)',
          backdropFilter: 'blur(20px) saturate(180%)',
          WebkitBackdropFilter: 'blur(20px) saturate(180%)',
        }}
      >
        <div className="bg-oracle-dark-gray px-5 py-4">
          <div className="flex items-start gap-4">
            <div className="min-w-0">
              <h2 id="create-eval-case-title" className="text-lg font-semibold text-white">
                New evaluation case
              </h2>
              <p className="mt-1 text-sm text-gray-200">Define a reusable question for the local evaluation loop.</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="ml-auto rounded-lg p-1.5 text-gray-200 transition-colors hover:bg-white/10"
              aria-label="Close evaluation case modal"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-4 bg-white px-6 pb-6 pt-5">
          <div className="app-scrollbar min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
            <div>
              <label htmlFor="eval-case-name" className="block text-xs font-semibold uppercase tracking-wide text-oracle-light-gray">
                Name
              </label>
              <input
                id="eval-case-name"
                autoFocus
                className="input-oracle mt-1"
                value={caseName}
                onChange={(event) => onCaseNameChange(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="eval-case-category" className="block text-xs font-semibold uppercase tracking-wide text-oracle-light-gray">
                Category
              </label>
              <select
                id="eval-case-category"
                className="input-oracle mt-1"
                value={caseCategory}
                onChange={(event) => onCaseCategoryChange(event.target.value)}
              >
                {EVAL_CATEGORY_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-oracle-light-gray">
                Groups the case for review; it does not change retrieval.
              </p>
            </div>
            <div>
              <label htmlFor="eval-case-question" className="block text-xs font-semibold uppercase tracking-wide text-oracle-light-gray">
                Question
              </label>
              <textarea
                id="eval-case-question"
                className="input-oracle mt-1 min-h-[120px] resize-y"
                value={caseQuestion}
                onChange={(event) => onCaseQuestionChange(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="eval-case-terms" className="block text-xs font-semibold uppercase tracking-wide text-oracle-light-gray">
                Expected terms
              </label>
              <input
                id="eval-case-terms"
                className="input-oracle mt-1"
                value={caseTerms}
                onChange={(event) => onCaseTermsChange(event.target.value)}
                placeholder="comma separated"
              />
              <p className="mt-1 text-xs text-oracle-light-gray">
                Optional words or phrases that should appear in a passing answer.
              </p>
            </div>
            <div>
              <label htmlFor="eval-case-minimum-citations" className="block text-xs font-semibold uppercase tracking-wide text-oracle-light-gray">
                Minimum citations
              </label>
              <input
                id="eval-case-minimum-citations"
                className="input-oracle mt-1"
                type="number"
                min={0}
                max={8}
                value={minimumCitations}
                onChange={(event) => onMinimumCitationsChange(Number(event.target.value || 0))}
              />
            </div>
          </div>

          <div className="flex shrink-0 justify-end gap-3 border-t border-gray-100 pt-4">
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button type="button" className="btn-primary" disabled={saving || !canSave} onClick={onSave}>
              {saving ? 'Saving...' : 'Save case'}
            </button>
          </div>
        </div>
      </div>
    </ModalPortal>
  );
}
