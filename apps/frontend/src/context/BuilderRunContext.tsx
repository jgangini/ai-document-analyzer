import { createContext, useContext, useState, type ReactNode } from 'react';

export interface RunProgressFile {
  filename: string;
  nodeStatus: Record<string, { status: string; error?: string; file_id?: string }>;
}

export interface BuilderRunContextValue {
  executeResult: any;
  setExecuteResult: (v: any) => void;
  runProgress: { files: RunProgressFile[] } | null;
  setRunProgress: (v: { files: RunProgressFile[] } | null) => void;
}

const BuilderRunContext = createContext<BuilderRunContextValue | undefined>(undefined);

/**
 * Mantiene el estado de ejecución del Builder (Run) al cambiar de página.
 * Al volver a Builder el botón Run sigue mostrando "Running" y el progreso se mantiene.
 */
export function BuilderRunProvider({ children }: { children: ReactNode }) {
  const [executeResult, setExecuteResult] = useState<any>(null);
  const [runProgress, setRunProgress] = useState<{ files: RunProgressFile[] } | null>(null);

  return (
    <BuilderRunContext.Provider value={{ executeResult, setExecuteResult, runProgress, setRunProgress }}>
      {children}
    </BuilderRunContext.Provider>
  );
}

export function useBuilderRun(): BuilderRunContextValue {
  const ctx = useContext(BuilderRunContext);
  if (ctx === undefined) {
    throw new Error('useBuilderRun must be used within a BuilderRunProvider');
  }
  return ctx;
}
