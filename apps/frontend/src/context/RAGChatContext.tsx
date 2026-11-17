import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';

interface RAGChatContextType {
  isSearchOpen: boolean;
  activeConversationId: number | null;
  activeConversationTitle: string | null;
  filterDocId: string | null;
  filterDocName: string | null;
  openGlobal: () => void;
  openSearch: () => void;
  closeSearch: () => void;
  openWithDoc: (docId: string | number, docName?: string | null) => void;
  openConversation: (conversationId: number, title?: string | null) => void;
  openNewConversation: () => void;
  attachConversation: (conversationId: number, title?: string | null) => void;
  closeChat: () => void;
}

const RAGChatContext = createContext<RAGChatContextType | undefined>(undefined);

export function RAGChatProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [activeConversationTitle, setActiveConversationTitle] = useState<string | null>(null);
  const [filterDocId, setFilterDocId] = useState<string | null>(null);
  const [filterDocName, setFilterDocName] = useState<string | null>(null);

  const openGlobal = () => {
    setIsSearchOpen(true);
    setFilterDocId(null);
    setFilterDocName(null);
  };

  const openSearch = () => {
    setIsSearchOpen(true);
  };

  const closeSearch = () => {
    setIsSearchOpen(false);
  };

  const openConversation = (conversationId: number, title?: string | null) => {
    setActiveConversationId(conversationId);
    setActiveConversationTitle(title ?? null);
    setFilterDocId(null);
    setFilterDocName(null);
    setIsSearchOpen(false);
    navigate('/chat');
  };

  const openNewConversation = () => {
    setActiveConversationId(null);
    setActiveConversationTitle(null);
    setFilterDocId(null);
    setFilterDocName(null);
    setIsSearchOpen(false);
    navigate('/chat');
  };

  const attachConversation = (conversationId: number, title?: string | null) => {
    setActiveConversationId(conversationId);
    if (title !== undefined) {
      setActiveConversationTitle(title);
    }
  };

  const openWithDoc = (docId: string | number, docName?: string | null) => {
    setActiveConversationId(null);
    setActiveConversationTitle(null);
    setFilterDocId(String(docId));
    setFilterDocName(docName ?? null);
    setIsSearchOpen(false);
    navigate('/chat');
  };

  const closeChat = () => {
    setFilterDocId(null);
    setFilterDocName(null);
    navigate('/home');
  };

  const value = useMemo<RAGChatContextType>(
    () => ({
      isSearchOpen,
      activeConversationId,
      activeConversationTitle,
      filterDocId,
      filterDocName,
      openGlobal,
      openSearch,
      closeSearch,
      openWithDoc,
      openConversation,
      openNewConversation,
      attachConversation,
      closeChat,
    }),
    [
      isSearchOpen,
      activeConversationId,
      activeConversationTitle,
      filterDocId,
      filterDocName,
    ]
  );

  return <RAGChatContext.Provider value={value}>{children}</RAGChatContext.Provider>;
}

export function useRAGChat(): RAGChatContextType {
  const context = useContext(RAGChatContext);
  if (!context) {
    throw new Error('useRAGChat must be used within RAGChatProvider');
  }
  return context;
}
