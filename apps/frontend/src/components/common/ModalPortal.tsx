import { createPortal } from 'react-dom';

interface ModalPortalProps {
  children: React.ReactNode;
  className?: string;
  zIndex?: string;
  onBackdropClick?: () => void;
}

export function ModalPortal({
  children,
  className = '',
  zIndex = 'z-50',
  onBackdropClick,
}: ModalPortalProps) {
  return createPortal(
    <div
      className={`fixed inset-0 m-0 bg-black/30 backdrop-blur-sm flex items-center justify-center ${zIndex} ${className}`}
      onClick={onBackdropClick}
    >
      {children}
    </div>,
    document.body
  );
}
