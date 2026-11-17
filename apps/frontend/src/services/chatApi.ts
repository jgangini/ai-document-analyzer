import api from './apiClient';

export const chatApi = {
  listConversations: (search?: string) =>
    api.get('/chats', {
      params: search ? { search } : undefined,
    }),
  createConversation: (title?: string) => api.post('/chats', { title }),
  renameConversation: (conversationId: number, title: string) =>
    api.patch(`/chats/${conversationId}`, { title }),
  deleteConversation: (conversationId: number) => api.delete(`/chats/${conversationId}`),
  getMessages: (conversationId: number) => api.get(`/chats/${conversationId}/messages`),
  exportConversation: (conversationId: number, format: 'markdown' | 'json' = 'markdown') =>
    api.get(`/chats/${conversationId}/export`, {
      params: { format },
      responseType: format === 'markdown' ? 'blob' : 'json',
    }),
};
