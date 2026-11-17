export type ChatConversationSummary = {
  conversation_id: number;
  title: string;
  turns: number;
  last_message_preview: string;
  created_at: string;
  updated_at: string;
};

export type ReasoningStage = {
  key: string;
  label: string;
  starts_at_seconds: number;
};

export type ReasoningResult = {
  strategy: string;
  answer_mode: string;
  visual_confirmation_used: boolean;
  analyzed_pages: number[];
  confidence_notes: string[];
};

export type ChatSource = {
  doc_id: string;
  name: string;
  source_number?: number;
  file_id?: number;
  page_number?: number;
  object_name_page?: string;
  snippet?: string;
};

export type GraphNodeDefinition = {
  key: string;
  label: string;
  kind: string;
};

export type GraphEdgeDefinition = {
  source: string;
  target: string;
  condition?: string;
};

export type GraphDefinition = {
  nodes: GraphNodeDefinition[];
  edges: GraphEdgeDefinition[];
  start_node: string;
  end_node: string;
};

export type RAGScopeOptions = {
  files: string[];
  metadata_fields: string[];
  has_metadata: boolean;
};

export type GraphRuntimeEvent = {
  event_type: string;
  thread_id?: string;
  timestamp?: string;
  langgraph_type?: string;
  node_key?: string;
  status?: string;
  payload?: any;
  state_patch?: Record<string, any>;
  execution?: Record<string, any>;
  final_response?: Record<string, any>;
  error?: string;
  duration_ms?: number;
};

export type SummaryMode = 'default' | 'per_document';

export type ChatRequestOptions = {
  allow_inferred_scope?: boolean;
  top_k?: number;
  candidate_k?: number;
  min_pages_per_selected_doc?: number;
  summary_mode?: SummaryMode;
  metadata_mode?: 'auto' | 'metadata_first';
  archive_slugs?: string[];
  metadata_fields?: string[];
};

export type UploadPreparationItem = {
  source_path: string;
  source_zip_path?: string | null;
  group_source_path: string;
  group_name: string;
  group_kind: string;
  archive_slug: string;
  file_name: string;
  display_name: string;
  document_code?: string | null;
  document_code_source: string;
  document_language: string;
  access: string;
  order: number;
  enabled: boolean;
};

export type UploadPreparationGroup = {
  group_source_path: string;
  group_name: string;
  group_kind: string;
  archive_slug: string;
  item_count: number;
  items: UploadPreparationItem[];
};

export type UploadPreparationError = {
  source_path: string;
  source_name: string;
  error: string;
};

export type UploadPreparationResponse = {
  groups: UploadPreparationGroup[];
  errors: UploadPreparationError[];
};

export type MetadataUploadMatchSummary = {
  matched_files: string[];
  unmatched_files: string[];
  duplicate_files: string[];
};

export type MetadataUploadResponse = {
  metadata_upload_id: string;
  source_file_name: string;
  display_name: string;
  description: string;
  access_scope: 'private' | 'all';
  metadata_status: string;
  created_at: string;
  columns: string[];
  total_rows: number;
  match_summary: MetadataUploadMatchSummary;
};

export type MetadataUploadSummary = {
  metadata_upload_id: string;
  owner_user_id: number;
  source_file_name: string;
  display_name: string;
  description: string;
  access_scope: 'private' | 'all';
  metadata_status: string;
  columns: string[];
  total_rows: number;
  row_count: number;
  matched_files_count: number;
  unmatched_files_count: number;
  linked_documents_count: number;
  created_at: string;
  updated_at: string;
};

export type MetadataUploadRowPreview = {
  file: string;
  fields: Record<string, unknown>;
};

export type MetadataUploadListResponse = {
  items: MetadataUploadSummary[];
};

export type MetadataUploadDetailResponse = MetadataUploadSummary & {
  rows: MetadataUploadRowPreview[];
};

export type MetadataUploadUpdateRequest = {
  display_name?: string | null;
  description?: string | null;
  metadata_status?: 'active' | 'archived';
  access_scope?: 'private' | 'all';
};

export type ImprovementRouteSummary = {
  route: string;
  count: number;
};

export type ImprovementOverview = {
  trace_count: number;
  completed_count: number;
  failed_count: number;
  running_count: number;
  avg_cited_sources: number;
  avg_evidence_sources: number;
  routes: ImprovementRouteSummary[];
  recent_feedback_count: number;
  eval_case_count: number;
  eval_run_count: number;
  checkpoint_thread_count: number;
  checkpoint_count: number;
  checkpoint_write_count: number;
};

export type ImprovementTraceRun = {
  trace_id: string;
  thread_id: string;
  user_id?: number | null;
  conversation_id?: number | null;
  question: string;
  status: string;
  answerability_route: string;
  answer_preview: string;
  cited_sources_count: number;
  evidence_sources_count: number;
  metadata: Record<string, any>;
  error: string;
  started_at: string;
  finished_at: string;
};

export type ImprovementTraceStep = {
  step_id: number;
  trace_id: string;
  node: string;
  status: string;
  payload: Record<string, any>;
  state_patch: Record<string, any>;
  duration_ms: number;
  error: string;
  created_at: string;
};

export type ImprovementFeedbackEvent = {
  feedback_event_id: number;
  user_id?: number | null;
  conversation_id?: number | null;
  trace_id: string;
  event_type: string;
  value: string;
  assistant_message_id: string;
  user_prompt: string;
  assistant_answer_preview: string;
  metadata: Record<string, any>;
  created_at: string;
};

export type ImprovementEvalCase = {
  eval_case_id: number;
  name: string;
  category: string;
  question: string;
  expected: Record<string, any>;
  source: string;
  created_at: string;
};

export type ImprovementEvalRun = {
  eval_run_id: number;
  name: string;
  status: string;
  metadata: Record<string, any>;
  started_at: string;
  finished_at: string;
  result_count: number;
  avg_score: number;
  passed_count: number;
};

export type ImprovementEvalResult = {
  eval_result_id: number;
  eval_run_id: number;
  eval_case_id: number;
  case_name: string;
  question: string;
  trace_id: string;
  status: string;
  score: number;
  details: Record<string, any>;
  created_at: string;
};

export type ImprovementCheckpointThread = {
  thread_id: string;
  checkpoint_count: number;
  write_count: number;
  trace_count: number;
  latest_trace_id: string;
  latest_question: string;
  last_checkpoint_at: string;
  created_at: string;
  updated_at: string;
};
