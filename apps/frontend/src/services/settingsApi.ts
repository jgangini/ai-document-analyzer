import api from './apiClient';

export const settingsApi = {
  getPublic: () => api.get('/settings/public'),
  get: () => api.get('/settings'),
  update: (updates: any) => api.put('/settings', { updates }),
  uploadAgentAvatar: (file: File) => {
    const payload = new FormData();
    payload.append('file', file);
    return api.post('/settings/agent-avatar', payload);
  },
  deleteAgentAvatar: () => api.delete('/settings/agent-avatar'),
};
