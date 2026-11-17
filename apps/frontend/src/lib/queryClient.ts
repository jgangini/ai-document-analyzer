import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60 * 1000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export const queryKeys = {
  setup: { check: ['setup', 'check'] as const },
  users: { me: ['users', 'me'] as const, list: ['users', 'list'] as const, groups: ['users', 'groups'] as const },
  chats: {
    all: (sessionScope: string | number) => ['chat-conversations', String(sessionScope)] as const,
    sidebar: (sessionScope: string | number) =>
      ['chat-conversations', String(sessionScope), 'sidebar'] as const,
    searchModal: (sessionScope: string | number) =>
      ['chat-conversations', String(sessionScope), 'search-modal'] as const,
    messages: (sessionScope: string | number, conversationId: number) =>
      ['chat-messages', String(sessionScope), conversationId] as const,
  },
  rag: {
    documents: (sessionScope: string | number) => ['rag-documents', String(sessionScope)] as const,
    scopeOptions: (sessionScope: string | number) => ['rag-scope-options', String(sessionScope)] as const,
  },
  metadata: {
    uploads: (sessionScope: string | number) => ['metadata-uploads', String(sessionScope)] as const,
    detail: (sessionScope: string | number, metadataUploadId: string) =>
      ['metadata-upload-detail', String(sessionScope), metadataUploadId] as const,
  },
  models: { list: ['models'] as const },
  workflow: { list: ['workflow', 'workflows'] as const, count: ['workflow', 'count'] as const },
  modelsProjects: ['models', 'projects'] as const,
  workflowExecutions: ['workflow', 'executions'] as const,
  builder: { projects: ['builder', 'projects'] as const },
  ocr: { activeModels: ['ocr', 'activeModels'] as const, recent: ['ocr', 'recent'] as const },
};
