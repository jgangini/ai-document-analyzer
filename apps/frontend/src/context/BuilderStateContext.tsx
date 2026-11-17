import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';

export interface BuilderStateContextValue {
  nodeFiles: Record<string, File[]>;
  setNodeFiles: (nodeId: string, files: File[]) => void;
  clearNodeFiles: () => void;
}

const BuilderStateContext = createContext<BuilderStateContextValue | undefined>(undefined);

/**
 * Mantiene los archivos adjuntos del Builder al cambiar de página (Workflows, etc.).
 * Al volver a Builder los archivos pendientes siguen ahí.
 */
export function BuilderStateProvider({ children }: { children: ReactNode }) {
  const [nodeFiles, setNodeFilesState] = useState<Record<string, File[]>>({});

  const setNodeFiles = useCallback((nodeId: string, files: File[]) => {
    setNodeFilesState((prev) => ({ ...prev, [nodeId]: files }));
  }, []);

  const clearNodeFiles = useCallback(() => {
    setNodeFilesState({});
  }, []);

  return (
    <BuilderStateContext.Provider value={{ nodeFiles, setNodeFiles, clearNodeFiles }}>
      {children}
    </BuilderStateContext.Provider>
  );
}

export function useBuilderState(): BuilderStateContextValue {
  const ctx = useContext(BuilderStateContext);
  if (ctx === undefined) {
    throw new Error('useBuilderState must be used within a BuilderStateProvider');
  }
  return ctx;
}
