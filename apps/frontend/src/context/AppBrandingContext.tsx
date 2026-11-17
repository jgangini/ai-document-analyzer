import { createContext, useContext, type ReactNode } from 'react';

const DEFAULT_CONTEXT_APP_NAME = 'AI Document Analyzer';

const AppBrandingContext = createContext(DEFAULT_CONTEXT_APP_NAME);

type AppBrandingProviderProps = {
  appName: string;
  children: ReactNode;
};

export function AppBrandingProvider({ appName, children }: AppBrandingProviderProps) {
  return (
    <AppBrandingContext.Provider value={appName || DEFAULT_CONTEXT_APP_NAME}>
      {children}
    </AppBrandingContext.Provider>
  );
}

export function useResolvedAppName() {
  return useContext(AppBrandingContext);
}
