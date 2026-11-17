import { createPortal } from 'react-dom';

export interface ToastItemData {
  id: number;
  message: string;
}

interface ToastProps {
  toasts: ToastItemData[];
  exitingIds?: Set<number>;
  onDismiss: (id: number) => void;
}

export function Toast({ toasts, exitingIds = new Set(), onDismiss }: ToastProps) {
  if (toasts.length === 0) return null;

  const content = (
    <div
      className="fixed left-1/2 -translate-x-1/2 bottom-12 z-[99999] flex flex-col gap-2 max-w-sm w-full sm:max-w-md pointer-events-auto"
      aria-live="polite"
      role="region"
      aria-label="Notificaciones"
    >
      {toasts.map(({ id, message }) => (
        <div
          key={id}
          className={`rounded-lg px-3 py-2 flex items-center gap-2 shadow-lg text-white min-h-[33px] ${exitingIds.has(id) ? 'toast-exit' : 'toast-enter'}`}
          style={{
            backgroundColor: '#2a2724',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.3)',
            fontSize: '11px',
          }}
          role="alert"
        >
          <span className="flex-1">{message}</span>
          <button
            type="button"
            onClick={() => onDismiss(id)}
            className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded text-white/80 hover:text-white hover:bg-white/10 transition-colors font-medium leading-none text-xs"
            aria-label="Cerrar"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );

  return createPortal(content, document.body);
}
