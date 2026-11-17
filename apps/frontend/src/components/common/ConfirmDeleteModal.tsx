import type { ReactNode } from 'react';

import { ConfirmModal } from './ConfirmModal';

interface ConfirmDeleteModalProps {
  title: string;
  message: ReactNode;
  detail?: string;
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
}

export function ConfirmDeleteModal({
  title,
  message,
  detail,
  onConfirm,
  onCancel,
  loading = false,
}: ConfirmDeleteModalProps) {
  return (
    <ConfirmModal
      icon={
        <svg className="w-10 h-10 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
        </svg>
      }
      iconBg="bg-red-100"
      iconRing="ring-red-50"
      title={title}
      message={message}
      detail={detail}
      confirmText="Delete"
      confirmClass="bg-oracle-red text-white hover:bg-oracle-red/90"
      loadingText="Deleting..."
      onConfirm={onConfirm}
      onCancel={onCancel}
      loading={loading}
    />
  );
}
