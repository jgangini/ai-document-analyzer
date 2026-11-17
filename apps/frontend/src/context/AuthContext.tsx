import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { queryClient, queryKeys } from '../lib/queryClient';

interface User {
  user_id: number;
  username: string;
  name: string;
  last_name: string;
  email: string;
  modules: number[];
  group_id: number;
  group_name: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
  isAdmin: boolean;
  loading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

async function requestAuthJson<T>(
  path: string,
  options: { method?: string; token?: string | null; body?: Record<string, unknown> } = {}
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: options.method || 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      detail = String(payload?.detail || detail);
    } catch {
      // Keep the HTTP status fallback.
    }
    const error = new Error(detail) as Error & { response?: { status: number; data: { detail: string } } };
    error.response = { status: response.status, data: { detail } };
    throw error;
  }
  return response.json() as Promise<T>;
}

function clearSessionCaches() {
  queryClient.removeQueries({ queryKey: ['chat-conversations'] });
  queryClient.removeQueries({ queryKey: ['chat-messages'] });
  queryClient.removeQueries({ queryKey: ['rag-documents'] });
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'));

  const { data: user, isPending: userLoading, isError } = useQuery({
    queryKey: [...queryKeys.users.me, token],
    queryFn: () => requestAuthJson<User>('/user/me', { token }),
    enabled: !!token,
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

  useEffect(() => {
    if (!!token && !userLoading && isError) {
      setToken(null);
      localStorage.removeItem('token');
      clearSessionCaches();
      queryClient.removeQueries({ queryKey: queryKeys.users.me });
    }
  }, [token, userLoading, isError]);

  const login = async (username: string, password: string) => {
    const response = await requestAuthJson<{ access_token: string; user: User }>('/auth/login', {
      method: 'POST',
      body: { username, password },
    });
    const { access_token, user: userData } = response;
    clearSessionCaches();
    queryClient.removeQueries({ queryKey: queryKeys.users.me });
    setToken(access_token);
    localStorage.setItem('token', access_token);
    queryClient.setQueryData([...queryKeys.users.me, access_token], userData);
  };

  const logout = () => {
    clearSessionCaches();
    setToken(null);
    localStorage.removeItem('token');
    sessionStorage.removeItem('builder-last-flow-id');
    sessionStorage.removeItem('flow-builder-state');
    queryClient.removeQueries({ queryKey: queryKeys.users.me });
  };

  const loading = !!token && userLoading;
  const isAuthenticated = !!token && !!user;
  const isAdmin = !!user && user.group_id === 0;

  return (
    <AuthContext.Provider
      value={{ user: user ?? null, token, login, logout, isAuthenticated, isAdmin, loading }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
}
