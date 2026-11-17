export function getInitials(name: string): string {
  return name
    .split(' ')
    .map((n) => n[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

export function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export type Source = {
  doc_id: string;
  name: string;
  source_number?: number;
  file_id?: number;
  page_number?: number;
  object_name_page?: string;
  snippet?: string;
};

export type ReasoningResult = {
  strategy: string;
  answer_mode: string;
  visual_confirmation_used: boolean;
  analyzed_pages: number[];
  confidence_notes: string[];
};

export type Message = {
  messageId: string;
  role: 'user' | 'assistant';
  text: string;
  timestamp: Date;
  localOnly?: boolean;
  modelUsed?: string;
  citedSources?: Source[];
  error?: string;
  reasoning?: ReasoningResult;
  telemetry?: Record<string, any>;
};

export type FeedbackKind = 'up' | 'down';

export type NodeRuntimeStatus = 'idle' | 'running' | 'completed' | 'failed';

export type NodeRuntimeState = {
  status: NodeRuntimeStatus;
  startedAt?: string;
  endedAt?: string;
  durationMs?: number;
  lastEventType?: string;
  error?: string;
};

export type GraphRenderNode = {
  key: string;
  label: string;
  kind: string;
  level: number;
  x: number;
  y: number;
  width: number;
};

export type GraphEdgePath = {
  source: string;
  target: string;
  condition: string;
  points: Array<{ x: number; y: number }>;
};
