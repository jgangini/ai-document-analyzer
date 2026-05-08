import { useNavigate, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { useHeaderSession } from '../../context/HeaderSessionContext';
import { useRAGChat } from '../../context/RAGChatContext';
import { handleUnauthorizedApiResponse } from '../../lib/apiAuthFailure';
import { sortChatConversationsByUpdatedAt } from '../../lib/chatSorting';
import { queryKeys } from '../../lib/queryClient';

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

type RouteMenuItem = {
  id: string;
  name: string;
  icon: JSX.Element;
  path: string;
};

type ActionMenuItem = {
  id: string;
  name: string;
  icon: JSX.Element;
  action: 'chat' | 'search_chats';
};

type MenuItem = RouteMenuItem | ActionMenuItem;

type SidebarChatSummary = {
  conversation_id: number;
  title: string;
  created_at: string;
  updated_at: string;
};

async function listSidebarConversations(): Promise<SidebarChatSummary[]> {
  const token = localStorage.getItem('token');
  const response = await fetch('/api/chats', {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  handleUnauthorizedApiResponse(response, '/chats');
  if (!response.ok) {
    throw new Error(`Failed to load chats (${response.status})`);
  }
  const payload = await response.json();
  return (payload?.items || []) as SidebarChatSummary[];
}

function parseChatTimestamp(value: string): Date | null {
  const rawValue = String(value || '').trim();
  if (!rawValue) return null;

  const directDate = new Date(rawValue);
  if (!Number.isNaN(directDate.getTime()) && /(?:z|[+-]\d{2}:\d{2})$/i.test(rawValue)) {
    return directDate;
  }

  const normalizedValue = rawValue.includes(' ') ? rawValue.replace(' ', 'T') : rawValue;
  const utcDate = new Date(`${normalizedValue}Z`);
  if (!Number.isNaN(utcDate.getTime())) {
    return utcDate;
  }

  return Number.isNaN(directDate.getTime()) ? null : directDate;
}

function formatRelativeUpdatedAt(value: string): string {
  const date = parseChatTimestamp(value);
  if (!date) return '';
  if (Number.isNaN(date.getTime())) return '';
  const deltaMs = Date.now() - date.getTime();
  if (!Number.isFinite(deltaMs)) return '';

  const normalizedDeltaMs = deltaMs < 0 ? 0 : deltaMs;

  const minuteMs = 60_000;
  const hourMs = 60 * minuteMs;
  const dayMs = 24 * hourMs;

  if (normalizedDeltaMs < hourMs) {
    const minutes = Math.max(1, Math.floor(normalizedDeltaMs / minuteMs));
    return `${minutes}m`;
  }
  if (normalizedDeltaMs < dayMs) {
    const hours = Math.max(1, Math.floor(normalizedDeltaMs / hourMs));
    return `${hours}h`;
  }
  if (normalizedDeltaMs < 7 * dayMs) {
    const days = Math.max(1, Math.floor(normalizedDeltaMs / dayMs));
    return `${days}d`;
  }

  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${month}/${day}`;
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const HEADER_HEIGHT_PX = 56;
  const FOOTER_HEIGHT_PX = 34;
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useHeaderSession();
  const isAuthenticated = Boolean(user);
  const {
    openNewConversation,
    openSearch,
    openConversation,
    activeConversationId,
  } = useRAGChat();

  const topMenuItems: MenuItem[] = [
    {
      id: 'home',
      name: 'Home',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
        </svg>
      ),
      path: '/home'
    },
    {
      id: 'chat',
      name: 'New chat',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.5 8.25V18A2.25 2.25 0 0117.25 20.25H6.75A2.25 2.25 0 014.5 18V6A2.25 2.25 0 016.75 3.75H14.25" />
        </svg>
      ),
      action: 'chat' as const
    },
    {
      id: 'search_chats',
      name: 'Search chats',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M21 21l-4.35-4.35m1.85-5.15a7 7 0 11-14 0 7 7 0 0114 0z"
          />
        </svg>
      ),
      action: 'search_chats' as const
    },
    {
      id: 'open_rag',
      name: 'RAG',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M8 10h8m-8 4h5m-9 6h16a1 1 0 001-1V7a1 1 0 00-1-1h-4l-2-2H10L8 6H4a1 1 0 00-1 1v12a1 1 0 001 1z"
          />
        </svg>
      ),
      path: '/rag'
    },
  ];

  const bottomMenuItems: RouteMenuItem[] = [
    {
      id: 'improvement',
      name: 'Observability',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M4 19V5m0 14h16M8 16v-5m4 5V8m4 8v-7M7 7l4 3 4-5 4 3"
          />
        </svg>
      ),
      path: '/observability'
    },
    {
      id: 'metadata',
      name: 'Metadata',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M4 6.75A2.75 2.75 0 016.75 4h10.5A2.75 2.75 0 0120 6.75v10.5A2.75 2.75 0 0117.25 20H6.75A2.75 2.75 0 014 17.25V6.75zM4 9h16M9 4v16"
          />
        </svg>
      ),
      path: '/metadata'
    },
    {
      id: 'settings',
      name: 'Settings',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 15.5a3.5 3.5 0 100-7 3.5 3.5 0 000 7zm7-3.5a7 7 0 00-.1-1.18l1.55-1.21a.75.75 0 00.18-.96l-1.47-2.55a.75.75 0 00-.9-.33l-1.86.75a6.95 6.95 0 00-2.04-1.18L14.08 3.3a.75.75 0 00-.74-.6h-2.94a.75.75 0 00-.74.6l-.28 1.98a6.95 6.95 0 00-2.04 1.18l-1.86-.75a.75.75 0 00-.9.33l-1.47 2.55a.75.75 0 00.18.96l1.55 1.21a7.84 7.84 0 000 2.36l-1.55 1.21a.75.75 0 00-.18.96l1.47 2.55a.75.75 0 00.9.33l1.86-.75a6.95 6.95 0 002.04 1.18l.28 1.98a.75.75 0 00.74.6h2.94a.75.75 0 00.74-.6l.28-1.98a6.95 6.95 0 002.04-1.18l1.86.75a.75.75 0 00.9-.33l1.47-2.55a.75.75 0 00-.18-.96l-1.55-1.21c.06-.39.1-.78.1-1.18z"
          />
        </svg>
      ),
      path: '/settings'
    },
    {
      id: 'users',
      name: 'Users',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
        </svg>
      ),
      path: '/users'
    },
  ];

  const recentChatsQuery = useQuery({
    queryKey: queryKeys.chats.sidebar(user?.user_id ?? 'anonymous'),
    queryFn: async () => {
      return sortChatConversationsByUpdatedAt(await listSidebarConversations());
    },
    enabled: isAuthenticated && !collapsed,
  });

  const renderMenuButton = (item: MenuItem) => {
    if (item.id === 'users' && user?.group_id !== 0) {
      return null;
    }

    const isActive = 'path' in item ? location.pathname === item.path : false;

    return (
      <button
        key={item.id}
        onClick={() => {
          if ('path' in item) {
            navigate(item.path);
            return;
          }
          if ('action' in item && item.action === 'chat') {
            openNewConversation();
            return;
          }
          if ('action' in item && item.action === 'search_chats') {
            openSearch();
          }
        }}
        className={`w-full flex items-center gap-3 transition-colors ${
          collapsed
            ? 'px-3 py-3 justify-center'
            : 'px-4 py-3 justify-start'
        } ${
          isActive
            ? 'bg-oracle-red/95 text-white shadow-[0_10px_24px_rgba(199,70,52,0.22)]'
            : 'text-gray-300 hover:bg-white/[0.07] hover:text-gray-100'
        }`}
        title={collapsed ? item.name : undefined}
      >
        <div className="flex-shrink-0">{item.icon}</div>
        {!collapsed && (
          <span className="text-xs font-medium">
            {item.name}
          </span>
        )}
      </button>
    );
  };

  return (
    <div
      className={`app-sidebar text-white transition-all duration-300 ${
        collapsed ? 'w-16' : 'w-52'
      } flex flex-col fixed left-0 z-40`}
      style={{ 
        top: `${HEADER_HEIGHT_PX}px`,
        height: `calc(100vh - ${HEADER_HEIGHT_PX}px - ${FOOTER_HEIGHT_PX}px)`,
        borderRight: '1px solid rgba(255, 255, 255, 0.1)',
        boxShadow: '2px 0 10px rgba(0, 0, 0, 0.2)'
      }}
    >
      {/* Toggle Button */}
      <button
        onClick={onToggle}
        className={`sidebar-toggle-button flex items-center gap-3 text-gray-300 transition-colors hover:bg-white/[0.07] hover:text-gray-100 ${
          collapsed ? 'px-3 py-3 justify-center' : 'px-4 py-3 justify-start'
        }`}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        <svg
          className={`w-5 h-5 transition-transform ${collapsed ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
        </svg>
      </button>

      {/* Menu Items */}
      <nav className="flex-1 py-2 flex flex-col min-h-0">
        <div className="shrink-0">
          {topMenuItems.map((item) => renderMenuButton(item))}
        </div>

        {!collapsed && (
          <section className="mt-2 min-h-0 flex-1 flex flex-col" aria-labelledby="sidebar-chats-heading">
            <div className="flex shrink-0 items-center justify-between px-4 pb-2">
              <p id="sidebar-chats-heading" className="text-sm font-medium text-white/90">
                Chats
              </p>
            </div>
            <div className="sidebar-chat-scroll min-h-0 flex-1 overflow-y-auto px-2">
              <div className="space-y-0.5 pb-2">
                {recentChatsQuery.isLoading ? (
                  <p className="px-2 py-2 text-xs text-gray-400">Loading chats...</p>
                ) : recentChatsQuery.isError ? (
                  <p className="px-2 text-xs text-red-300">No se pudieron cargar los chats</p>
                ) : (recentChatsQuery.data || []).length === 0 ? (
                  <p className="px-2 text-xs text-gray-400">No chats yet</p>
                ) : (
                  (recentChatsQuery.data || []).map((chat) => {
                    const isActiveChat =
                      location.pathname === '/chat' && activeConversationId === chat.conversation_id;
                    return (
                      <button
                        key={chat.conversation_id}
                        type="button"
                        className={`w-full rounded-xl px-3 py-2 text-left transition-colors ${
                          isActiveChat
                            ? 'bg-white/10 text-white'
                            : 'text-gray-100 hover:bg-white/5'
                        }`}
                        onClick={() => openConversation(chat.conversation_id, chat.title)}
                        title={chat.title}
                      >
                        <span className="flex items-center gap-2">
                          <span className="min-w-0 flex-1 truncate text-sm leading-5">
                            {chat.title}
                          </span>
                          <span className="shrink-0 text-[11px] font-medium text-gray-400">
                            {formatRelativeUpdatedAt(chat.updated_at)}
                          </span>
                        </span>
                      </button>
                    );
                  })
                )}
              </div>
            </div>
          </section>
        )}

        <div className={`mt-auto pb-4 ${collapsed ? '' : 'pt-2 border-t border-white/10'}`}>
          {bottomMenuItems.map((item) => renderMenuButton(item))}
        </div>
      </nav>
    </div>
  );
}
