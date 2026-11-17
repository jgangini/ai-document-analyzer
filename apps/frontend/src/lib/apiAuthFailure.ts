export function handleUnauthorizedApiResponse(response: { status: number }, requestPath: string) {
  if (response.status !== 401 || requestPath.includes('/auth/login')) {
    return;
  }

  localStorage.removeItem('token');
  sessionStorage.removeItem('builder-last-flow-id');
  sessionStorage.removeItem('flow-builder-state');
  window.location.href = '/login';
}
