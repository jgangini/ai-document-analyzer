import type { CSSProperties, ReactNode } from 'react';

import { ModalPortal } from './ModalPortal';

interface GlassModalProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  zIndex?: string;
  containerClassName?: string;
  panelClassName?: string;
  panelStyle?: CSSProperties;
}

export function GlassModal({
  open,
  onClose,
  children,
  zIndex = 'z-[300]',
  containerClassName = 'items-start justify-center p-4',
  panelClassName = '',
  panelStyle,
}: GlassModalProps) {
  if (!open) return null;

  return (
    <ModalPortal zIndex={zIndex} className={containerClassName} onBackdropClick={onClose}>
      <div
        className={`rounded-2xl shadow-2xl border border-white/20 overflow-hidden ${panelClassName}`}
        style={{
          background: 'rgba(255,255,255,0.72)',
          backdropFilter: 'blur(20px) saturate(180%)',
          WebkitBackdropFilter: 'blur(20px) saturate(180%)',
          ...panelStyle,
        }}
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </ModalPortal>
  );
}
