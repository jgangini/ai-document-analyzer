import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Layout } from '../common/Layout';
import { LoadingState } from '../common/LoadingState';
import { useToast } from '../../context/ToastContext';
import { useAuth } from '../../context/AuthContext';
import { type ImprovementEvalCase } from '../../services/apiTypes';
import { improvementApi } from '../../services/improvementApi';
import { CreateEvalCaseModal } from './improvement/CreateEvalCaseModal';
import { ImprovementCheckpointsTab } from './improvement/ImprovementCheckpointsTab';
import { ImprovementEvalsTab } from './improvement/ImprovementEvalsTab';
import { ImprovementFeedbackTab } from './improvement/ImprovementFeedbackTab';
import { ImprovementTracesTab } from './improvement/ImprovementTracesTab';
import { MetricTile } from './improvement/ImprovementBadges';
import {
  CHECKPOINTS_PAGE_SIZE,
  DEFAULT_EVAL_CATEGORY,
  EVAL_CASES_PAGE_SIZE,
  IMPROVEMENT_TABS,
  formatPercent,
  parseTerms,
  type ImprovementTab,
} from './improvement/Improvement.model';

export function ContinuousImprovement() {
  const { user } = useAuth();
  const sessionScope = user?.user_id ?? 'anonymous';
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<ImprovementTab>('traces');
  const [selectedTraceId, setSelectedTraceId] = useState('');
  const [selectedCaseIds, setSelectedCaseIds] = useState<number[]>([]);
  const [caseName, setCaseName] = useState('');
  const [caseCategory, setCaseCategory] = useState(DEFAULT_EVAL_CATEGORY);
  const [caseQuestion, setCaseQuestion] = useState('');
  const [caseTerms, setCaseTerms] = useState('');
  const [minimumCitations, setMinimumCitations] = useState(1);
  const [showCreateCaseModal, setShowCreateCaseModal] = useState(false);
  const [selectedEvalRunId, setSelectedEvalRunId] = useState<number | null>(null);
  const [evalCasesPage, setEvalCasesPage] = useState(1);
  const [checkpointsPage, setCheckpointsPage] = useState(1);

  const overviewQuery = useQuery({
    queryKey: ['improvement', 'overview', sessionScope],
    queryFn: () => improvementApi.getOverview(),
  });
  const tracesQuery = useQuery({
    queryKey: ['improvement', 'traces', sessionScope],
    queryFn: () => improvementApi.listTraces(40),
  });
  const traceStepsQuery = useQuery({
    queryKey: ['improvement', 'trace-steps', selectedTraceId],
    queryFn: () => improvementApi.listTraceSteps(selectedTraceId, 240),
    enabled: Boolean(selectedTraceId),
  });
  const feedbackQuery = useQuery({
    queryKey: ['improvement', 'feedback', sessionScope],
    queryFn: () => improvementApi.listFeedback(40),
  });
  const evalCasesQuery = useQuery({
    queryKey: ['improvement', 'eval-cases', sessionScope],
    queryFn: () => improvementApi.listEvalCases(160),
  });
  const evalRunsQuery = useQuery({
    queryKey: ['improvement', 'eval-runs', sessionScope],
    queryFn: () => improvementApi.listEvalRuns(30),
  });
  const evalResultsQuery = useQuery({
    queryKey: ['improvement', 'eval-results', selectedEvalRunId],
    queryFn: () => improvementApi.listEvalResults(Number(selectedEvalRunId), 100),
    enabled: Boolean(selectedEvalRunId),
  });
  const checkpointsQuery = useQuery({
    queryKey: ['improvement', 'checkpoints', sessionScope],
    queryFn: () => improvementApi.listCheckpoints(100),
  });

  const selectedTrace = useMemo(() => {
    return (tracesQuery.data?.data.items || []).find((item) => item.trace_id === selectedTraceId) || null;
  }, [selectedTraceId, tracesQuery.data?.data.items]);

  const createCaseMutation = useMutation({
    mutationFn: () =>
      improvementApi.createEvalCase({
        name: caseName.trim(),
        category: caseCategory.trim() || 'manual',
        question: caseQuestion.trim(),
        source: 'ui',
        expected: {
          requires_citations: true,
          minimum_citations: minimumCitations,
          must_include_terms: parseTerms(caseTerms),
          pass_threshold: 0.8,
        },
      }),
    onSuccess: () => {
      setCaseName('');
      setCaseCategory(DEFAULT_EVAL_CATEGORY);
      setCaseQuestion('');
      setCaseTerms('');
      setMinimumCitations(1);
      setShowCreateCaseModal(false);
      queryClient.invalidateQueries({ queryKey: ['improvement', 'eval-cases', sessionScope] });
      queryClient.invalidateQueries({ queryKey: ['improvement', 'overview', sessionScope] });
      showToast('Evaluation case saved', 'success');
    },
    onError: (error: any) => {
      showToast(String(error?.response?.data?.detail || error?.message || 'Could not save evaluation case'), 'error');
    },
  });

  const runEvalMutation = useMutation({
    mutationFn: () =>
      improvementApi.createEvalRun({
        name: `UI evaluation ${new Date().toLocaleString()}`,
        case_ids: selectedCaseIds,
        top_k: 5,
      }),
    onSuccess: (response) => {
      const runId = Number(response?.data?.eval_run_id || 0);
      if (runId > 0) setSelectedEvalRunId(runId);
      queryClient.invalidateQueries({ queryKey: ['improvement', 'eval-runs', sessionScope] });
      queryClient.invalidateQueries({ queryKey: ['improvement', 'eval-results'] });
      queryClient.invalidateQueries({ queryKey: ['improvement', 'traces', sessionScope] });
      queryClient.invalidateQueries({ queryKey: ['improvement', 'checkpoints', sessionScope] });
      queryClient.invalidateQueries({ queryKey: ['improvement', 'overview', sessionScope] });
      showToast('Evaluation run completed', 'success');
    },
    onError: (error: any) => {
      showToast(String(error?.response?.data?.detail || error?.message || 'Could not run evaluation'), 'error');
    },
  });

  const overview = overviewQuery.data?.data;
  const traces = tracesQuery.data?.data.items || [];
  const feedback = feedbackQuery.data?.data.items || [];
  const evalCases = evalCasesQuery.data?.data.items || [];
  const evalRuns = evalRunsQuery.data?.data.items || [];
  const evalResults = evalResultsQuery.data?.data.items || [];
  const checkpoints = checkpointsQuery.data?.data.items || [];
  const evalCasesTotalPages = Math.max(1, Math.ceil(evalCases.length / EVAL_CASES_PAGE_SIZE));
  const safeEvalCasesPage = Math.min(evalCasesPage, evalCasesTotalPages);
  const evalCasesStartIndex = (safeEvalCasesPage - 1) * EVAL_CASES_PAGE_SIZE;
  const evalCasesEndIndex = Math.min(evalCasesStartIndex + EVAL_CASES_PAGE_SIZE, evalCases.length);
  const paginatedEvalCases = evalCases.slice(evalCasesStartIndex, evalCasesEndIndex);
  const checkpointsTotalPages = Math.max(1, Math.ceil(checkpoints.length / CHECKPOINTS_PAGE_SIZE));
  const safeCheckpointsPage = Math.min(checkpointsPage, checkpointsTotalPages);
  const checkpointsStartIndex = (safeCheckpointsPage - 1) * CHECKPOINTS_PAGE_SIZE;
  const checkpointsEndIndex = Math.min(checkpointsStartIndex + CHECKPOINTS_PAGE_SIZE, checkpoints.length);
  const paginatedCheckpoints = checkpoints.slice(checkpointsStartIndex, checkpointsEndIndex);

  useEffect(() => {
    if (selectedEvalRunId || evalRuns.length === 0) return;
    setSelectedEvalRunId(evalRuns[0].eval_run_id);
  }, [evalRuns, selectedEvalRunId]);

  useEffect(() => {
    setCheckpointsPage(1);
    setEvalCasesPage(1);
  }, [activeTab]);

  useEffect(() => {
    if (evalCasesPage > evalCasesTotalPages) {
      setEvalCasesPage(evalCasesTotalPages);
    }
  }, [evalCasesPage, evalCasesTotalPages]);

  useEffect(() => {
    if (checkpointsPage > checkpointsTotalPages) {
      setCheckpointsPage(checkpointsTotalPages);
    }
  }, [checkpointsPage, checkpointsTotalPages]);

  useEffect(() => {
    if (!showCreateCaseModal) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setShowCreateCaseModal(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showCreateCaseModal]);

  const passRate = useMemo(() => {
    const total = Number(overview?.completed_count || 0) + Number(overview?.failed_count || 0);
    if (!total) return 0;
    return Number(overview?.completed_count || 0) / total;
  }, [overview?.completed_count, overview?.failed_count]);

  const toggleCase = (evalCase: ImprovementEvalCase) => {
    setSelectedCaseIds((prev) =>
      prev.includes(evalCase.eval_case_id)
        ? prev.filter((item) => item !== evalCase.eval_case_id)
        : [...prev, evalCase.eval_case_id]
    );
  };

  const openTraceFromEval = (traceId: string) => {
    const normalizedTraceId = String(traceId || '').trim();
    if (!normalizedTraceId) return;
    setSelectedTraceId(normalizedTraceId);
    setActiveTab('traces');
  };

  const canSaveCase = Boolean(caseName.trim() && caseQuestion.trim());

  if (overviewQuery.isLoading) {
    return (
      <Layout>
        <LoadingState className="py-8" label="Loading settings..." textClassName="text-oracle-light-gray" />
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="flex min-h-[calc(100vh-10rem)] flex-col gap-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="app-page-title text-3xl font-bold">Observability</h1>
            <p className="app-page-description mt-1 text-sm">
              Local traces, feedback, evaluations, and checkpoint visibility for the document graph.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              queryClient.invalidateQueries({ queryKey: ['improvement'] });
              showToast('Improvement data refreshed', 'success');
            }}
            className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg border border-transparent bg-oracle-red px-4 text-sm font-medium text-white transition-colors hover:bg-oracle-red/90"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v6h6M20 20v-6h-6M5 19a8 8 0 0013-3M19 5A8 8 0 006 8" />
            </svg>
            Refresh
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
          <MetricTile label="Traces" value={String(overview?.trace_count ?? 0)} detail={`${overview?.running_count ?? 0} running`} />
          <MetricTile label="Completed" value={String(overview?.completed_count ?? 0)} detail={formatPercent(passRate)} />
          <MetricTile label="Avg Citations" value={(overview?.avg_cited_sources ?? 0).toFixed(1)} detail="cited sources" />
          <MetricTile label="Feedback" value={String(overview?.recent_feedback_count ?? 0)} detail="user signals" />
          <MetricTile label="Eval Cases" value={String(overview?.eval_case_count ?? 0)} detail={`${overview?.eval_run_count ?? 0} runs`} />
          <MetricTile
            label="Checkpoints"
            value={String(overview?.checkpoint_count ?? 0)}
            detail={`${overview?.checkpoint_thread_count ?? 0} threads`}
          />
        </div>

        <div className="app-light-surface flex min-h-0 flex-1 flex-col rounded-lg border border-oracle-border bg-white shadow-sm">
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-oracle-border px-4 pt-3">
            {IMPROVEMENT_TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`border-b-2 px-4 py-2 text-sm font-semibold transition ${
                  activeTab === tab.id
                    ? 'border-oracle-red text-oracle-red'
                    : 'border-transparent text-oracle-medium-gray hover:text-oracle-dark-gray'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {activeTab === 'traces' ? (
            <ImprovementTracesTab
              traces={traces}
              selectedTrace={selectedTrace}
              selectedTraceId={selectedTraceId}
              traceSteps={traceStepsQuery.data?.data.items || []}
              loadingTraceSteps={traceStepsQuery.isLoading}
              onSelectTrace={setSelectedTraceId}
            />
          ) : null}

          {activeTab === 'evals' ? (
            <ImprovementEvalsTab
              evalCases={evalCases}
              paginatedEvalCases={paginatedEvalCases}
              selectedCaseIds={selectedCaseIds}
              startIndex={evalCasesStartIndex}
              endIndex={evalCasesEndIndex}
              currentPage={safeEvalCasesPage}
              totalPages={evalCasesTotalPages}
              runPending={runEvalMutation.isPending}
              evalRuns={evalRuns}
              selectedEvalRunId={selectedEvalRunId}
              evalResults={evalResults}
              evalResultsLoading={evalResultsQuery.isLoading}
              onToggleCase={toggleCase}
              onOpenCreateCase={() => setShowCreateCaseModal(true)}
              onRunSelected={() => runEvalMutation.mutate()}
              onPageChange={setEvalCasesPage}
              onSelectRun={setSelectedEvalRunId}
              onOpenTrace={openTraceFromEval}
            />
          ) : null}

          {activeTab === 'feedback' ? (
            <ImprovementFeedbackTab feedback={feedback} />
          ) : null}

          {activeTab === 'checkpoints' ? (
            <ImprovementCheckpointsTab
              checkpoints={checkpoints}
              paginatedCheckpoints={paginatedCheckpoints}
              startIndex={checkpointsStartIndex}
              endIndex={checkpointsEndIndex}
              currentPage={safeCheckpointsPage}
              totalPages={checkpointsTotalPages}
              onPageChange={setCheckpointsPage}
              onOpenTrace={openTraceFromEval}
            />
          ) : null}
        </div>

        {showCreateCaseModal ? (
          <CreateEvalCaseModal
            caseName={caseName}
            caseCategory={caseCategory}
            caseQuestion={caseQuestion}
            caseTerms={caseTerms}
            minimumCitations={minimumCitations}
            canSave={canSaveCase}
            saving={createCaseMutation.isPending}
            onCaseNameChange={setCaseName}
            onCaseCategoryChange={setCaseCategory}
            onCaseQuestionChange={setCaseQuestion}
            onCaseTermsChange={setCaseTerms}
            onMinimumCitationsChange={setMinimumCitations}
            onClose={() => setShowCreateCaseModal(false)}
            onSave={() => createCaseMutation.mutate()}
          />
        ) : null}
      </div>
    </Layout>
  );
}
