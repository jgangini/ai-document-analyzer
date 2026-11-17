import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useAuth } from '../../context/AuthContext';
import { useRAGChat } from '../../context/RAGChatContext';
import { sortChatConversationsByUpdatedAt } from '../../lib/chatSorting';
import { queryKeys } from '../../lib/queryClient';
import { useToast } from '../../context/ToastContext';
import { chatApi } from '../../services/chatApi';
import type { ChatConversationSummary } from '../../services/apiTypes';
import { GlassModal } from './GlassModal';
import { LoadingState } from './LoadingState';

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  const hh = String(date.getHours()).padStart(2, '0');
  const min = String(date.getMinutes()).padStart(2, '0');
  const ss = String(date.getSeconds()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd} ${hh}:${min}:${ss}`;
}

function normalizeForSearch(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function highlightSearchMatch(text: string, search: string) {
  const source = String(text || '');
  const query = search.trim();
  if (!query) return source;
  const regex = new RegExp(`(${escapeRegExp(query)})`, 'ig');
  const segments = source.split(regex);
  return (
    <>
      {segments.map((segment, index) => {
        const isMatch = segment.toLowerCase() === query.toLowerCase();
        if (!isMatch) return <span key={`txt-${index}`}>{segment}</span>;
        return (
          <mark key={`mark-${index}`} className="bg-yellow-200 px-0.5 rounded-sm text-inherit">
            {segment}
          </mark>
        );
      })}
    </>
  );
}

export function SearchChatsModal() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { user, isAuthenticated } = useAuth();
  const { isSearchOpen, closeSearch, openConversation } = useRAGChat();
  const [search, setSearch] = useState('');
  const [editingConversationId, setEditingConversationId] = useState<number | null>(null);
  const [editingTitle, setEditingTitle] = useState('');

  const conversationsQuery = useQuery({
    queryKey: queryKeys.chats.searchModal(user?.user_id ?? 'anonymous'),
    queryFn: async () => {
      const response = await chatApi.listConversations();
      return sortChatConversationsByUpdatedAt(
        (response.data?.items || []) as ChatConversationSummary[]
      );
    },
    enabled: isAuthenticated && isSearchOpen,
  });

  const filteredConversations = (conversationsQuery.data || []).filter((conversation) => {
    const term = normalizeForSearch(search);
    if (!term) return true;
    const haystack = normalizeForSearch(
      `${conversation.title || ''} ${conversation.last_message_preview || ''}`
    );
    return haystack.includes(term);
  });

  const renameMutation = useMutation({
    mutationFn: ({ conversationId, title }: { conversationId: number; title: string }) =>
      chatApi.renameConversation(conversationId, title),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.chats.all(user?.user_id ?? 'anonymous') });
      setEditingConversationId(null);
      setEditingTitle('');
      showToast('Chat renamed successfully', 'success');
    },
    onError: () => {
      showToast('Failed to rename chat', 'error');
    },
  });

  const handleDownload = async (conversationId: number, title: string) => {
    try {
      const response = await chatApi.exportConversation(conversationId, 'markdown');
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      const safeTitle = (title || 'chat').replace(/[^\w\- ]/g, '').trim().replace(/\s+/g, '_');
      link.href = url;
      link.download = `${safeTitle || 'chat'}.md`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch {
      showToast('Failed to download chat', 'error');
    }
  };

  return (
    <GlassModal
      open={isSearchOpen}
      onClose={closeSearch}
      containerClassName="items-start justify-center p-4"
      panelClassName="w-full max-w-4xl mt-16 border-0"
    >
      <div className="px-5 py-4 flex items-center gap-3 bg-oracle-dark-gray">
        <h2 className="text-lg font-semibold text-white">Search Chats</h2>
        <div className="ml-auto" />
        <button
          type="button"
          onClick={closeSearch}
          className="p-1.5 rounded-lg hover:bg-white/10 transition-colors text-gray-200"
          aria-label="Close search chats"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="p-4 space-y-3" style={{ background: 'rgba(255,255,255,0.75)' }}>
        <input
          type="text"
          className="input-oracle w-full"
          placeholder="Search chats..."
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />

        <div className="max-h-[60vh] overflow-y-auto overflow-x-hidden rounded-xl border border-white/30 bg-white/70">
          {conversationsQuery.isLoading ? (
            <LoadingState
              size="sm"
              label="Loading chats..."
              className="p-4"
              textClassName="text-oracle-light-gray"
            />
          ) : filteredConversations.length === 0 ? (
            <p className="text-sm text-oracle-light-gray p-4">No chats found.</p>
          ) : (
            <ul>
              {filteredConversations.map((conversation) => (
                <li key={conversation.conversation_id} className="border-b border-gray-200/70 last:border-b-0">
                  <div className="flex items-center gap-2 px-3 py-2.5 hover:bg-gray-50/70 min-w-0">
                    <button
                      type="button"
                      className="flex-1 min-w-0 text-left"
                      onClick={() => {
                        openConversation(conversation.conversation_id, conversation.title);
                        closeSearch();
                      }}
                    >
                      {editingConversationId === conversation.conversation_id ? (
                        <input
                          type="text"
                          className="input-oracle w-full"
                          value={editingTitle}
                          onClick={(event) => event.stopPropagation()}
                          onChange={(event) => setEditingTitle(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                              const title = editingTitle.trim();
                              if (!title) return;
                              renameMutation.mutate({
                                conversationId: conversation.conversation_id,
                                title,
                              });
                            }
                          }}
                        />
                      ) : (
                        <>
                          <p className="text-sm font-medium text-oracle-dark-gray truncate">
                            {highlightSearchMatch(conversation.title, search)}
                          </p>
                          <p className="text-xs text-oracle-medium-gray truncate">
                            {conversation.last_message_preview
                              ? highlightSearchMatch(conversation.last_message_preview, search)
                              : 'No messages yet'}
                          </p>
                          <p className="text-[11px] text-oracle-light-gray mt-1">
                            {conversation.turns} turn(s) · Updated {formatDateTime(conversation.updated_at)}
                          </p>
                        </>
                      )}
                    </button>

                    {editingConversationId === conversation.conversation_id ? (
                      <>
                        <button
                          type="button"
                          className="btn-primary"
                          disabled={renameMutation.isPending || !editingTitle.trim()}
                          onClick={() =>
                            renameMutation.mutate({
                              conversationId: conversation.conversation_id,
                              title: editingTitle.trim(),
                            })
                          }
                        >
                          Save
                        </button>
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => {
                            setEditingConversationId(null);
                            setEditingTitle('');
                          }}
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="p-1.5 rounded hover:bg-gray-200/70 text-oracle-medium-gray"
                          title="Rename chat"
                          onClick={() => {
                            setEditingConversationId(conversation.conversation_id);
                            setEditingTitle(conversation.title);
                          }}
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                          </svg>
                        </button>
                        <button
                          type="button"
                          className="p-1.5 rounded hover:bg-gray-200/70 text-oracle-medium-gray"
                          title="Download chat"
                          onClick={() => handleDownload(conversation.conversation_id, conversation.title)}
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                          </svg>
                        </button>
                      </>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

      </div>
    </GlassModal>
  );
}
