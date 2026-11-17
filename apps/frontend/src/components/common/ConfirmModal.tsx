import type { ReactNode } from 'react';

import { ModalPortal } from './ModalPortal';

interface ConfirmModalProps {
  icon: ReactNode;
  iconBg?: string;
  iconRing?: string;
  title: string;
  message: ReactNode;
  detail?: string;
  confirmText: string;
  confirmClass?: string;
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
  loadingText?: string;
}

export function ConfirmModal({
  icon,
  iconBg = 'bg-gray-100',
  iconRing = 'ring-gray-50',
  title,
  message,
  detail,
  confirmText,
  confirmClass = 'text-oracle-red hover:bg-red-50',
  onConfirm,
  onCancel,
  loading = false,
  loadingText = 'Processing...',
}: ConfirmModalProps) {
  return (
    <ModalPortal>
      <div className="bg-white rounded-2xl w-full max-w-sm shadow-2xl overflow-hidden">
        <div className="flex w-full min-w-0 flex-col items-center pt-8 pb-6 px-6 text-center">
          <div className={`w-20 h-20 rounded-full ${iconBg} flex items-center justify-center mb-5 ring-8 ${iconRing}`}>
            {icon}
          </div>
          <h2 className="text-xl font-bold text-oracle-dark-gray">{title}</h2>
          <div className="mt-2 w-full min-w-0 max-w-full text-sm leading-relaxed text-oracle-medium-gray">
            {message}
          </div>
          {detail && (
            <p className="text-xs text-oracle-light-gray mt-1">{detail}</p>
          )}
        </div>
        <div className="flex">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className="flex-1 py-4 text-sm font-medium text-oracle-medium-gray hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Cancel
          </button>
          <div className="w-px bg-gray-100" />
          <button
            type="button"
            onClick={onConfirm}
            disabled={loading}
            className={`flex-1 py-4 text-sm font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${confirmClass}`}
          >
            {loading ? loadingText : confirmText}
          </button>
        </div>
      </div>
    </ModalPortal>
  );
}
