import { createContext, useContext, type ReactNode } from 'react';

type HeaderSessionUser = {
  user_id: number;
  username: string;
  group_id: number;
};

type HeaderSessionContextValue = {
  user: HeaderSessionUser | null;
  logout: () => void;
};

const HeaderSessionContext = createContext<HeaderSessionContextValue>({
  user: null,
  logout: () => undefined,
});

type HeaderSessionProviderProps = {
  user: HeaderSessionUser | null;
  logout: () => void;
  children: ReactNode;
};

export function HeaderSessionProvider({ user, logout, children }: HeaderSessionProviderProps) {
  return (
    <HeaderSessionContext.Provider value={{ user, logout }}>
      {children}
    </HeaderSessionContext.Provider>
  );
}

export function useHeaderSession() {
  return useContext(HeaderSessionContext);
}
