import { useEffect } from 'react';

import { SearchChatsModal } from '../components/common/SearchChatsModal';
import { AppBrandingProvider } from '../context/AppBrandingContext';
import { useAuth } from '../context/AuthContext';
import { HeaderSessionProvider } from '../context/HeaderSessionContext';
import { RAGChatProvider } from '../context/RAGChatContext';
import { useAppBranding } from '../hooks/useAppBranding';
import { AppRouter } from './AppRouter';

export function SessionScopedApp() {
  const { user, token, logout } = useAuth();
  const { appName } = useAppBranding();
  const sessionScope = user?.user_id ?? token ?? 'anonymous';

  useEffect(() => {
    document.title = appName;
  }, [appName]);

  return (
    <AppBrandingProvider appName={appName}>
      <HeaderSessionProvider
        user={user ? { user_id: user.user_id, username: user.username, group_id: user.group_id } : null}
        logout={logout}
      >
        <RAGChatProvider key={String(sessionScope)}>
          <AppRouter />
          <SearchChatsModal />
        </RAGChatProvider>
      </HeaderSessionProvider>
    </AppBrandingProvider>
  );
}
