import api from './apiClient';
import type {
  ImprovementCheckpointThread,
  ImprovementEvalCase,
  ImprovementEvalResult,
  ImprovementEvalRun,
  ImprovementFeedbackEvent,
  ImprovementOverview,
  ImprovementTraceRun,
  ImprovementTraceStep,
} from './apiTypes';

export const improvementApi = {
  getOverview: () => api.get<ImprovementOverview>('/improvement/overview'),
  listTraces: (limit: number = 25) =>
    api.get<{ items: ImprovementTraceRun[] }>('/improvement/traces', {
      params: { limit },
    }),
  listTraceSteps: (traceId: string, limit: number = 200) =>
    api.get<{ items: ImprovementTraceStep[] }>(`/improvement/traces/${traceId}/steps`, {
      params: { limit },
    }),
  listFeedback: (limit: number = 25) =>
    api.get<{ items: ImprovementFeedbackEvent[] }>('/improvement/feedback', {
      params: { limit },
    }),
  recordFeedback: (payload: {
    event_type: string;
    value: string;
    conversation_id?: number | null;
    trace_id?: string | null;
    assistant_message_id: string;
    user_prompt: string;
    assistant_answer: string;
    metadata?: Record<string, any>;
  }) => api.post('/improvement/feedback', payload),
  listEvalCases: (limit: number = 100) =>
    api.get<{ items: ImprovementEvalCase[] }>('/improvement/eval-cases', {
      params: { limit },
    }),
  createEvalCase: (payload: {
    name: string;
    category: string;
    question: string;
    expected?: Record<string, any>;
    source?: string;
  }) => api.post<{ item: ImprovementEvalCase }>('/improvement/eval-cases', payload),
  listEvalRuns: (limit: number = 25) =>
    api.get<{ items: ImprovementEvalRun[] }>('/improvement/eval-runs', {
      params: { limit },
    }),
  createEvalRun: (payload: { name?: string; case_ids: number[]; top_k?: number }) =>
    api.post('/improvement/eval-runs', payload),
  listEvalResults: (runId: number, limit: number = 100) =>
    api.get<{ items: ImprovementEvalResult[] }>(`/improvement/eval-runs/${runId}/results`, {
      params: { limit },
    }),
  listCheckpoints: (limit: number = 25) =>
    api.get<{ items: ImprovementCheckpointThread[] }>('/improvement/checkpoints', {
      params: { limit },
    }),
};
