import { createContext, useContext, useState, useCallback, useRef, useEffect, type ReactNode } from 'react';
import { Toast } from '../components/common/Toast';

export interface ToastItem {
  id: number;
  message: string;
}

interface ToastContextType {
  showToast: (
    message: string,
    _variant?: 'success' | 'error' | 'info' | 'warning'
  ) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

const TOAST_DURATION_MS = 5000;
const TOAST_EXIT_MS = 400;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [exitingIds, setExitingIds] = useState<Set<number>>(new Set());
  const idRef = useRef(0);
  const timeoutsRef = useRef<Map<number, number>>(new Map());
  const exitTimeoutsRef = useRef<Map<number, number>>(new Map());

  const removeToastAfterExit = useCallback((id: number) => {
    const t = timeoutsRef.current.get(id);
    if (t != null) {
      clearTimeout(t);
      timeoutsRef.current.delete(id);
    }
    setExitingIds((prev) => new Set([...prev, id]));
    const exitT = window.setTimeout(() => {
      exitTimeoutsRef.current.delete(id);
      setToasts((prev) => prev.filter((x) => x.id !== id));
      setExitingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }, TOAST_EXIT_MS);
    exitTimeoutsRef.current.set(id, exitT);
  }, []);

  const dismissToast = useCallback((id: number) => {
    removeToastAfterExit(id);
  }, [removeToastAfterExit]);

  const showToast = useCallback(
    (
      message: string,
      _variant?: 'success' | 'error' | 'info' | 'warning'
    ) => {
      void _variant;
      const id = ++idRef.current;
      setToasts((prev) => [...prev, { id, message }]);
      const t = window.setTimeout(() => {
        timeoutsRef.current.delete(id);
        removeToastAfterExit(id);
      }, TOAST_DURATION_MS);
      timeoutsRef.current.set(id, t);
    },
    [removeToastAfterExit]
  );

  useEffect(() => {
    return () => {
      timeoutsRef.current.forEach(clearTimeout);
      exitTimeoutsRef.current.forEach(clearTimeout);
    };
  }, []);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <Toast toasts={toasts} exitingIds={exitingIds} onDismiss={dismissToast} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextType {
  const ctx = useContext(ToastContext);
  if (ctx === undefined) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return ctx;
}
