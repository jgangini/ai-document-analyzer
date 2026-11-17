import { useEffect } from 'react';
import { Routes } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { LoadingState } from '../components/common/LoadingState';
import { useAuth } from '../context/AuthContext';
import { handleUnauthorizedApiResponse } from '../lib/apiAuthFailure';
import { queryClient, queryKeys } from '../lib/queryClient';
import { AuthenticatedRoutes } from './AuthenticatedRoutes';
import { SetupRoutes } from './SetupRoutes';

async function checkSetupCompleted(): Promise<boolean> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 10_000);
  try {
    const token = localStorage.getItem('token');
    const response = await fetch('/api/setup/check', {
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      signal: controller.signal,
    });
    handleUnauthorizedApiResponse(response, '/setup/check');
    if (!response.ok) return false;
    const payload = await response.json();
    return payload?.completed === true;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export function AppRouter() {
  const { isAuthenticated, loading, logout } = useAuth();
  const { data: setupCompleted, isPending: setupPending } = useQuery({
    queryKey: queryKeys.setup.check,
    queryFn: checkSetupCompleted,
    staleTime: Infinity,
    retry: false,
  });

  const setupDone = setupCompleted === true;
  const showSpinner = loading || setupPending;

  useEffect(() => {
    if (!setupPending && !setupDone && setupCompleted === false) logout();
  }, [setupPending, setupDone, setupCompleted, logout]);

  if (showSpinner) {
    const setupLoading = window.location.pathname === '/setup';
    return (
      <div
        className={
          setupLoading
            ? 'setup-shell-light flex min-h-screen items-center justify-center bg-oracle-bg-gray text-oracle-dark-gray'
            : 'app-shell-dark flex min-h-screen items-center justify-center'
        }
      >
        <LoadingState />
      </div>
    );
  }

  const handleSetupComplete = () => queryClient.setQueryData(queryKeys.setup.check, true);

  return (
    <Routes>
      {!setupDone ? (
        <SetupRoutes onSetupComplete={handleSetupComplete} />
      ) : (
        <AuthenticatedRoutes isAuthenticated={isAuthenticated} />
      )}
    </Routes>
  );
}
