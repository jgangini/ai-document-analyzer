import axios from 'axios';

import { handleUnauthorizedApiResponse } from '../lib/apiAuthFailure';

export const baseURL = '/api';

const api = axios.create({
  baseURL,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  if (config.data instanceof FormData) {
    delete config.headers['Content-Type'];
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      const requestUrl = error?.config?.url ?? '';
      handleUnauthorizedApiResponse(error.response, requestUrl);
    }
    return Promise.reject(error);
  }
);

export default api;
