import { useQuery } from '@tanstack/react-query';

import { DEFAULT_APP_DISPLAY_NAME } from '../config/branding';
import { settingsApi } from '../services/settingsApi';

function resolveApplicationName(payload: any): string {
  const configuredName = String(payload?.app?.name || '').trim();
  if (configuredName) {
    return configuredName;
  }
  return DEFAULT_APP_DISPLAY_NAME;
}

export const appBrandingQueryKey = ['settings', 'public-branding'] as const;

export function useAppBranding() {
  const query = useQuery({
    queryKey: appBrandingQueryKey,
    queryFn: () => settingsApi.getPublic(),
    staleTime: 60_000,
    retry: false,
  });

  return {
    ...query,
    appName: resolveApplicationName(query.data?.data),
  };
}
